from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from cfin_agents import document_store
from cfin_agents.analyst_summary import resolve_agent_summary
from cfin_agents.attachment_store import (
    ALLOWED_CONTENT_TYPES,
    MAX_ATTACHMENT_BYTES,
    read_attachment_bytes,
    save_attachment_bytes,
)
from cfin_agents.batch import (
    StagedDocumentRepository,
    bootstrap_demo,
    bootstrap_golden_document,
    diagnose_new_records,
    load_staging_records,
    load_tickets,
)
from cfin_agents.models import WorkflowRun, WorkflowStatus
from cfin_agents.observability import langfuse_status, langfuse_trace_url
from cfin_agents.paths import attachment_backend_name, runtime_data_dir
from cfin_agents.seed_queue import reset_workbench
from cfin_agents.services import ApprovalStore
from cfin_agents.sweep import sweep_agentic_batch
from cfin_agents.ticket_models import (
    OperatorStatus,
    SummaryFeedback,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketEvent,
    TicketStatus,
)
from cfin_agents.ticket_narratives import enrich_ticket, ticket_title
from cfin_agents.ticketing import (
    ROLE_ASSIGNEES,
    TICKET_STAGES,
    dashboard_summary,
    usd_equivalent,
)
from cfin_agents.timeutil import utc_now
from cfin_agents.workflow import AgenticWorkflow

load_dotenv()

app = FastAPI(title="FinHub Exception Workbench API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TransitionRequest(BaseModel):
    operator_status: OperatorStatus
    actor: str = "Workbench User"
    note: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_status(cls, data):
        if isinstance(data, dict) and "operator_status" not in data and "status" in data:
            data = {**data, "operator_status": data["status"]}
        return data


class CommentRequest(BaseModel):
    text: str
    author: str = "Workbench User"


class DescriptionUpdateRequest(BaseModel):
    description: str


class ApproveRequest(BaseModel):
    actor: str = "Workbench User"
    note: str | None = None


class MaintainMappingRequest(BaseModel):
    target_value: str
    source_value: str | None = None
    actor: str = "Workbench User"
    note: str | None = None


class AssigneeUpdateRequest(BaseModel):
    assignee: str
    actor: str = "Workbench User"


class SummaryFeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    note: str | None = None
    actor: str = "Workbench User"


class WorkbenchSweepRequest(BaseModel):
    batch_size: int = Field(default=5, ge=1, le=25)
    wait: bool = False


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "storage_backend": attachment_backend_name(),
        "data_dir": str(runtime_data_dir()),
        "langfuse": langfuse_status(),
    }


@app.post("/api/demo/bootstrap")
def bootstrap(count: int = 50, seed: int = 42):
    tickets = bootstrap_demo(count=count, seed=seed)
    return {
        "created_tickets": len(tickets),
        "dashboard": dashboard_summary(tickets).model_dump(mode="json"),
    }


@app.post("/api/demo/fresh-run")
def fresh_run(count: int = 50, seed: int = 42):
    tickets = bootstrap_demo(count=count, seed=seed)
    return {
        "created_tickets": len(tickets),
        "dashboard": dashboard_summary(tickets).model_dump(mode="json"),
    }


@app.post("/api/demo/golden-document")
def golden_document(document_id: str = "DOC-1001", approve: bool = False):
    ticket = bootstrap_golden_document(document_id=document_id, approve=approve)
    tickets = load_tickets()
    return {
        "document_id": document_id,
        "ticket_id": ticket.ticket_id,
        "agent_summary": ticket.agent_summary,
        "execution_mode": ticket.workflow_run.execution_mode,
        "summary_source": _summary_source_label(),
        "dashboard": dashboard_summary(tickets).model_dump(mode="json"),
    }


@app.post("/api/jobs/diagnose-new")
def diagnose_new():
    tickets = diagnose_new_records()
    return {
        "total_tickets": len(tickets),
        "dashboard": dashboard_summary(tickets).model_dump(mode="json"),
    }


@app.get("/api/workbench/status")
def workbench_status() -> dict:
    return {
        "ticket_count": document_store.ticket_count(),
        "staging_counts": document_store.staging_counts(),
        "summary_source": _summary_source_label(),
        "storage_backend": attachment_backend_name(),
        "data_dir": str(runtime_data_dir()),
        "langfuse": langfuse_status(),
    }


@app.post("/api/workbench/reset")
def workbench_reset(count: int = 50, seed: int = 42) -> dict:
    if count < 1 or count > 500:
        raise HTTPException(status_code=400, detail="count must be between 1 and 500.")
    result = reset_workbench(reseed_count=count, seed=seed)
    tickets = load_tickets()
    return {
        **result,
        "dashboard": dashboard_summary(tickets).model_dump(mode="json"),
    }


@app.post("/api/workbench/clear")
def workbench_clear() -> dict:
    result = reset_workbench(reseed_count=None)
    return {
        **result,
        "dashboard": dashboard_summary([]).model_dump(mode="json"),
    }


_SWEEP_JOBS: dict[str, dict] = {}
_SWEEP_JOBS_LOCK = threading.Lock()


def _sweep_result_payload(results: list[dict]) -> dict:
    tickets = load_tickets()
    created = [row for row in results if row.get("ticket_id")]
    errors = [row for row in results if row.get("error")]
    return {
        "processed": len(results),
        "created_tickets": len(created),
        "errors": errors,
        "results": results,
        "ticket_count": document_store.ticket_count(),
        "staging_counts": document_store.staging_counts(),
        "dashboard": dashboard_summary(tickets).model_dump(mode="json"),
    }


def _run_sweep_job(job_id: str, batch_size: int) -> None:
    def on_progress(processed: int, total: int, last: dict) -> None:
        with _SWEEP_JOBS_LOCK:
            job = _SWEEP_JOBS.get(job_id)
            if job is not None:
                job["processed"] = processed
                job["total"] = total
                job["last_result"] = last

    try:
        results = sweep_agentic_batch(batch_size=batch_size, progress_callback=on_progress)
        payload = _sweep_result_payload(results)
        with _SWEEP_JOBS_LOCK:
            _SWEEP_JOBS[job_id].update(status="completed", **payload)
    except Exception as exc:
        with _SWEEP_JOBS_LOCK:
            _SWEEP_JOBS[job_id].update(status="failed", error=str(exc))


@app.post("/api/workbench/sweep")
def workbench_sweep(request: WorkbenchSweepRequest) -> dict:
    if request.wait:
        results = sweep_agentic_batch(batch_size=request.batch_size)
        return {"status": "completed", **_sweep_result_payload(results)}

    job_id = f"SWEEP-{uuid4().hex[:8].upper()}"
    pending = document_store.staging_counts().get("new", 0)
    job = {
        "job_id": job_id,
        "status": "running",
        "processed": 0,
        "total": min(request.batch_size, pending),
        "batch_size": request.batch_size,
        "started_at": utc_now().isoformat(),
    }
    with _SWEEP_JOBS_LOCK:
        _SWEEP_JOBS[job_id] = job
        snapshot = dict(job)
    worker = threading.Thread(target=_run_sweep_job, args=(job_id, request.batch_size), daemon=True)
    worker.start()
    return snapshot


@app.get("/api/workbench/sweep/jobs/{job_id}")
def workbench_sweep_job(job_id: str) -> dict:
    with _SWEEP_JOBS_LOCK:
        job = _SWEEP_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown sweep job '{job_id}'")
        return dict(job)


@app.get("/api/workbench/assignees")
def workbench_assignees() -> dict:
    return {
        "assignees": [
            {"name": name, "role": role.value} for role, name in sorted(
                ROLE_ASSIGNEES.items(), key=lambda item: item[1]
            )
        ]
    }


@app.get("/api/tickets")
def tickets(
    operator_status: Annotated[OperatorStatus | None, Query(alias="status")] = None,
    owner_role: str | None = None,
    priority: str | None = None,
    reason_code: str | None = None,
) -> list[dict]:
    ticket_records = load_tickets()
    filtered = [
        ticket
        for ticket in ticket_records
        if _matches(ticket, operator_status, owner_role, priority, reason_code)
    ]
    return [_ticket_list_item(ticket) for ticket in filtered]


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: str) -> dict:
    ticket = _find_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Unknown ticket_id '{ticket_id}'")
    enriched = enrich_ticket(ticket)
    payload = enriched.model_dump(mode="json")
    payload["langfuse_trace_url"] = langfuse_trace_url(enriched.workflow_run.langfuse_trace_id)
    return payload


@app.post("/api/tickets/{ticket_id}/comments")
def add_ticket_comment(ticket_id: str, request: CommentRequest) -> Ticket:
    body = request.text.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Comment text cannot be empty.")

    ticket = _require_ticket(ticket_id)
    ticket.comments.append(
        TicketComment(
            comment_id=f"CMT-{uuid4().hex[:8].upper()}",
            author=request.author.strip() or "Workbench User",
            text=body,
            created_at=utc_now(),
        )
    )
    document_store.upsert_ticket(ticket)
    return enrich_ticket(ticket)


@app.patch("/api/tickets/{ticket_id}/description")
def update_ticket_description(ticket_id: str, request: DescriptionUpdateRequest) -> Ticket:
    body = request.description.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Description cannot be empty.")

    ticket = _require_ticket(ticket_id)
    ticket.title = body
    ticket.title_edited = True
    ticket.updated_at = utc_now()
    document_store.upsert_ticket(ticket)
    return enrich_ticket(ticket)


@app.patch("/api/tickets/{ticket_id}/assignee")
def update_ticket_assignee(ticket_id: str, request: AssigneeUpdateRequest) -> Ticket:
    assignee = request.assignee.strip()
    if not assignee:
        raise HTTPException(status_code=400, detail="Assignee cannot be empty.")

    ticket = _require_ticket(ticket_id)
    previous = ticket.assignee
    if previous == assignee:
        return enrich_ticket(ticket)

    now = utc_now()
    ticket.assignee = assignee
    ticket.updated_at = now
    ticket.timeline.append(
        TicketEvent(
            timestamp=now,
            actor=request.actor.strip() or "Workbench User",
            action="reassigned",
            details={"from_assignee": previous, "to_assignee": assignee},
            summary=f"Ticket reassigned from {previous} to {assignee}.",
        )
    )
    document_store.upsert_ticket(ticket)
    return enrich_ticket(ticket)


@app.post("/api/tickets/{ticket_id}/summary-feedback")
def submit_summary_feedback(ticket_id: str, request: SummaryFeedbackRequest) -> Ticket:
    ticket = _require_ticket(ticket_id)
    now = utc_now()
    actor = request.actor.strip() or "Workbench User"
    note = (request.note or "").strip()
    ticket.summary_feedback = SummaryFeedback(
        rating=request.rating,
        actor=actor,
        note=note,
        created_at=now,
    )
    document_store.upsert_ticket(ticket)
    _append_feedback_log(
        {
            "timestamp": now.isoformat(),
            "ticket_id": ticket.ticket_id,
            "document_id": ticket.document_id,
            "reason_code": ticket.reason_code,
            "rating": request.rating,
            "note": note,
            "actor": actor,
            "agent_summary": ticket.agent_summary,
        }
    )
    return enrich_ticket(ticket)


@app.post("/api/tickets/{ticket_id}/approve")
def approve_ticket(ticket_id: str, request: ApproveRequest) -> Ticket:
    ticket = _require_ticket(ticket_id)
    if ticket.workflow_run.status != WorkflowStatus.NEEDS_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail="Only tickets awaiting approval can be approved.",
        )

    run = _rerun_ticket_workflow(ticket, approve=True)
    now = utc_now()
    actor = request.actor.strip() or "Workbench User"
    note = (request.note or "").strip()

    ticket.workflow_run = run
    if run.agent_summary:
        ticket.agent_summary = run.agent_summary
    ticket.timeline.append(
        TicketEvent(
            timestamp=now,
            actor=actor,
            action="approval_recorded",
            details={"note": note},
            summary="Master data creation approved by a human reviewer.",
        )
    )

    reprocessed = bool(run.reprocess_result and run.reprocess_result.success)
    if reprocessed:
        target_id = run.reprocess_result.target_document_id
        previous_status = ticket.operator_status
        ticket.operator_status = OperatorStatus.RESOLVED
        ticket.timeline.append(
            TicketEvent(
                timestamp=now,
                actor="reprocessing_controller",
                action="reprocess_completed",
                from_status=_operator_as_journey(previous_status),
                to_status=TicketStatus.RESOLVED,
                details={"target_document_id": target_id},
                summary=f"Document reprocessed successfully as {target_id}. Ticket resolved.",
            )
        )
        comment_body = (
            f"Approved: master data creation signed off. Document reprocessed as {target_id}."
        )
        if note:
            comment_body = f"{comment_body} {note}"
        ticket.comments.append(
            TicketComment(
                comment_id=f"CMT-{uuid4().hex[:8].upper()}",
                author=actor,
                text=comment_body,
                created_at=now,
            )
        )

    ticket.updated_at = now
    ticket.current_stage_started_at = now
    document_store.upsert_ticket(ticket)
    return enrich_ticket(ticket)


_MAPPING_TYPE_BY_REASON_PREFIX: dict[str, str] = {
    "MP_GL_ACCOUNT": "gl_account",
    "MP_COST_CENTER": "cost_center",
    "MP_PROFIT_CENTER": "profit_center",
}


@app.post("/api/tickets/{ticket_id}/maintain-mapping")
def maintain_ticket_mapping(ticket_id: str, request: MaintainMappingRequest) -> Ticket:
    ticket = _require_ticket(ticket_id)
    mapping_type = next(
        (
            value
            for prefix, value in _MAPPING_TYPE_BY_REASON_PREFIX.items()
            if ticket.reason_code.startswith(prefix)
        ),
        None,
    )
    if mapping_type is None:
        raise HTTPException(
            status_code=400,
            detail="Mapping maintenance only applies to missing-mapping (MP_*) tickets.",
        )

    target_value = request.target_value.strip()
    if not target_value:
        raise HTTPException(status_code=400, detail="Target value cannot be empty.")

    source_value = (request.source_value or "").strip() or _source_value_for_ticket(
        ticket, mapping_type
    )

    run = _rerun_ticket_workflow(ticket, approve=False)
    now = utc_now()
    actor = request.actor.strip() or "Workbench User"
    note = (request.note or "").strip()

    ticket.workflow_run = run
    if run.agent_summary:
        ticket.agent_summary = run.agent_summary
    ticket.timeline.append(
        TicketEvent(
            timestamp=now,
            actor=actor,
            action="mapping_maintained",
            details={
                "mapping_type": mapping_type,
                "source_value": source_value,
                "target_value": target_value,
            },
            summary=(
                f"Source-to-target {mapping_type.replace('_', ' ')} mapping maintained: "
                f"{source_value} → {target_value}."
            ),
        )
    )

    reprocessed = bool(run.reprocess_result and run.reprocess_result.success)
    if reprocessed:
        target_id = run.reprocess_result.target_document_id
        previous_status = ticket.operator_status
        ticket.operator_status = OperatorStatus.RESOLVED
        ticket.timeline.append(
            TicketEvent(
                timestamp=now,
                actor="reprocessing_controller",
                action="reprocess_completed",
                from_status=_operator_as_journey(previous_status),
                to_status=TicketStatus.RESOLVED,
                details={"target_document_id": target_id},
                summary=f"Document reprocessed successfully as {target_id}. Ticket resolved.",
            )
        )
        comment_body = (
            f"Mapping maintained ({source_value} → {target_value}); "
            f"document reprocessed as {target_id}."
        )
        if note:
            comment_body = f"{comment_body} {note}"
        ticket.comments.append(
            TicketComment(
                comment_id=f"CMT-{uuid4().hex[:8].upper()}",
                author=actor,
                text=comment_body,
                created_at=now,
            )
        )

    ticket.updated_at = now
    ticket.current_stage_started_at = now
    document_store.upsert_ticket(ticket)
    return enrich_ticket(ticket)


@app.post("/api/tickets/{ticket_id}/attachments")
async def upload_ticket_attachment(
    ticket_id: str,
    file: Annotated[UploadFile, File()],
    actor: str = "Workbench User",
    purpose: str = "resolution_proof",
) -> Ticket:
    filename = (file.filename or "upload").strip()
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{content_type}'. "
                "Upload images, PDF, CSV, Excel, or text files."
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit.",
        )

    ticket = _require_ticket(ticket_id)
    now = utc_now()
    attachment_id = f"ATT-{uuid4().hex[:8].upper()}"
    save_attachment_bytes(ticket_id, attachment_id, filename, content)
    ticket.attachments.append(
        TicketAttachment(
            attachment_id=attachment_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            uploaded_at=now,
            uploaded_by=actor.strip() or "Workbench User",
            purpose=purpose.strip() or "resolution_proof",
        )
    )
    ticket.updated_at = now
    document_store.upsert_ticket(ticket)
    return enrich_ticket(ticket)


@app.get("/api/tickets/{ticket_id}/attachments/{attachment_id}")
def download_ticket_attachment(ticket_id: str, attachment_id: str) -> Response:
    ticket = _find_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Unknown ticket_id '{ticket_id}'")

    attachment = next(
        (item for item in ticket.attachments if item.attachment_id == attachment_id),
        None,
    )
    if not attachment:
        raise HTTPException(status_code=404, detail=f"Unknown attachment_id '{attachment_id}'")

    content = read_attachment_bytes(ticket_id, attachment_id, attachment.filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Attachment file not found in storage.")

    headers = {"Content-Disposition": f'inline; filename="{attachment.filename}"'}
    return Response(content=content, media_type=attachment.content_type, headers=headers)


@app.post("/api/tickets/{ticket_id}/transition")
def transition_ticket(ticket_id: str, request: TransitionRequest) -> Ticket:
    if request.operator_status == OperatorStatus.BLOCKED:
        note = (request.note or "").strip()
        if not note:
            raise HTTPException(
                status_code=400,
                detail="A comment is required when setting status to Blocked.",
            )

    if request.operator_status == OperatorStatus.RESOLVED and not request.attachment_ids:
        raise HTTPException(
            status_code=400,
            detail="At least one reprocessing proof attachment is required when resolving.",
        )

    ticket = _require_ticket(ticket_id)

    if request.operator_status == OperatorStatus.RESOLVED:
        known_ids = {item.attachment_id for item in ticket.attachments}
        missing = [item for item in request.attachment_ids if item not in known_ids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown attachment ids for ticket: {', '.join(missing)}",
            )

    previous = ticket.operator_status
    now = utc_now()
    actor = request.actor.strip() or "Workbench User"
    ticket.operator_status = request.operator_status
    ticket.updated_at = now
    ticket.current_stage_started_at = now

    if request.operator_status == OperatorStatus.BLOCKED:
        note = (request.note or "").strip()
        ticket.comments.append(
            TicketComment(
                comment_id=f"CMT-{uuid4().hex[:8].upper()}",
                author=actor,
                text=f"Blocked: {note}",
                created_at=now,
            )
        )

    if request.operator_status == OperatorStatus.RESOLVED:
        note = (request.note or "").strip()
        proof_names = [
            item.filename
            for item in ticket.attachments
            if item.attachment_id in request.attachment_ids
        ]
        comment_body = f"Resolved: reprocessing proof attached ({', '.join(proof_names)})."
        if note:
            comment_body = f"{comment_body} {note}"
        ticket.comments.append(
            TicketComment(
                comment_id=f"CMT-{uuid4().hex[:8].upper()}",
                author=actor,
                text=comment_body,
                created_at=now,
            )
        )

    ticket.timeline.append(
        TicketEvent(
            timestamp=now,
            actor=actor,
            action="manual_transition",
            from_status=_operator_as_journey(previous),
            to_status=_operator_as_journey(request.operator_status),
            details={
                "note": (request.note or "").strip(),
                "attachment_ids": request.attachment_ids,
            },
        )
    )
    document_store.upsert_ticket(ticket)
    return enrich_ticket(ticket)


@app.get("/api/dashboard/summary")
def dashboard():
    return dashboard_summary(load_tickets())


@app.get("/api/dashboard/stage-matrix")
def stage_matrix(limit: int = 100) -> dict:
    tickets = load_tickets()[:limit]
    stage_names = [stage.value for stage in TICKET_STAGES]
    return {
        "stages": stage_names,
        "rows": [
            {
                "ticket_id": ticket.ticket_id,
                "document_id": ticket.document_id,
                "operator_status": ticket.operator_status.value,
                "workflow_status": ticket.workflow_run.status.value,
                "owner_role": ticket.owner_role.value,
                "durations": ticket.stage_durations_days,
            }
            for ticket in tickets
        ],
    }


def _operator_as_journey(status: OperatorStatus) -> TicketStatus:
    return TicketStatus(status.value)


def _find_ticket(ticket_id: str) -> Ticket | None:
    return document_store.get_ticket(ticket_id)


def _require_ticket(ticket_id: str) -> Ticket:
    ticket = document_store.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticket_id '{ticket_id}'")
    return ticket


def _rerun_ticket_workflow(ticket: Ticket, *, approve: bool) -> WorkflowRun:
    """Re-run the governed workflow for a ticket's document.

    Runs the deterministic controller directly: an operator-triggered follow-up
    (approval, mapping maintenance) is a policy-controlled action, not a fresh
    agent investigation, and must return synchronously to the UI.
    """
    repository = StagedDocumentRepository(load_staging_records())
    workflow = AgenticWorkflow(repository=repository, approval_store=ApprovalStore())
    return workflow.run(
        document_id=ticket.document_id,
        approve=approve,
        force_deterministic=True,
    )


def _source_value_for_ticket(ticket: Ticket, mapping_type: str) -> str:
    record = next(
        (item for item in load_staging_records() if item.case_id == ticket.case_id),
        None,
    )
    if record is None:
        return "unknown"
    value = getattr(record.document, mapping_type, None)
    return value or "unknown"


def _append_feedback_log(record: dict) -> None:
    try:
        log_path = runtime_data_dir() / "summary_feedback.jsonl"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _matches(
    ticket: Ticket,
    operator_status: OperatorStatus | None,
    owner_role: str | None,
    priority: str | None,
    reason_code: str | None,
) -> bool:
    return (
        (operator_status is None or ticket.operator_status == operator_status)
        and (owner_role is None or ticket.owner_role.value == owner_role)
        and (priority is None or ticket.priority.value == priority)
        and (reason_code is None or ticket.reason_code == reason_code)
    )


def _ticket_list_item(ticket: Ticket) -> dict:
    agent_summary = resolve_agent_summary(
        ticket.workflow_run,
        persisted=ticket.agent_summary,
    )
    return {
        "ticket_id": ticket.ticket_id,
        "document_id": ticket.document_id,
        "source_document_ref": ticket.source_document_ref,
        "source_system": ticket.source_system,
        "title": ticket_title(ticket),
        "description": ticket_title(ticket),
        "reason_description": ticket.reason_description or ticket.reason_code,
        "company_code": ticket.company_code,
        "amount": ticket.amount,
        "currency": ticket.currency,
        "amount_usd": round(usd_equivalent(ticket.amount, ticket.currency), 2),
        "priority": ticket.priority.value,
        "operator_status": ticket.operator_status.value,
        "reason_code": ticket.reason_code,
        "error_type": ticket.error_type,
        "workflow_status": ticket.workflow_run.status.value,
        "owner_role": ticket.owner_role.value,
        "tagged_roles": [role.value for role in ticket.tagged_roles],
        "assignee": ticket.assignee,
        "agent_summary": agent_summary,
        "days_open": round((ticket.updated_at - ticket.created_at).total_seconds() / 86400, 1),
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "sla_due_at": ticket.sla_due_at.isoformat(),
    }


def _summary_source_label() -> str:
    use_llm = os.getenv("SUMMARY_USE_LLM", "0").lower() in {"1", "true", "yes"}
    disable_llm = os.getenv("DISABLE_LLM", "0").lower() in {"1", "true", "yes"}
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    if use_llm and has_key and not disable_llm:
        return f"llm:{os.getenv('SUMMARY_MODEL', 'gpt-4o')}"
    return "deterministic_eval_template"


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
