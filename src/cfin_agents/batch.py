from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from cfin_agents import document_store
from cfin_agents.repository import DATA_DIR, SyntheticRepository
from cfin_agents.services import ApprovalStore, DeterministicWorkflow
from cfin_agents.synthetic_generator import ERROR_CODES, generate_staged_failures
from cfin_agents.ticket_models import ErrorLog, StagedFailureRecord, StagingRecordStatus, Ticket
from cfin_agents.ticketing import create_ticket, dashboard_summary
from cfin_agents.workflow import AgenticWorkflow

STAGING_FILE = DATA_DIR / "staging_failures.json"
TICKETS_FILE = DATA_DIR / "tickets.json"


class StagedDocumentRepository(SyntheticRepository):
    """Repository view over staged documents plus the bundled reference data."""

    def __init__(self, records: list[StagedFailureRecord]) -> None:
        super().__init__()
        self._documents.update(
            {record.document.document_id: record.document for record in records}
        )


def seed_staging_records(count: int = 50, *, seed: int = 42) -> list[StagedFailureRecord]:
    records = generate_staged_failures(count=count, seed=seed)
    document_store.replace_staging_records(records)
    return records


def inject_new_records(count: int = 25, *, seed: int = 9001) -> list[StagedFailureRecord]:
    records = load_staging_records()
    next_index = len(records) + 1
    new_records = generate_staged_failures(count=count, seed=seed, start_index=next_index)
    records.extend(new_records)
    save_staging_records(records)
    return new_records


def diagnose_new_records(
    records: list[StagedFailureRecord] | None = None,
    existing_tickets: list[Ticket] | None = None,
) -> list[Ticket]:
    records = records or load_staging_records()
    tickets = load_tickets() if existing_tickets is None else list(existing_tickets)
    existing_case_ids = {ticket.case_id for ticket in tickets}
    repository = StagedDocumentRepository(records)
    workflow = DeterministicWorkflow(repository=repository, approval_store=ApprovalStore())

    with _without_openai_summary_calls():
        for record in records:
            if record.status != StagingRecordStatus.NEW or record.case_id in existing_case_ids:
                continue
            try:
                run = workflow.run(
                    record.document.document_id,
                    approve=False,
                    execution_mode="batch_deterministic",
                )
                ticket = create_ticket(record, run)
                record.status = StagingRecordStatus.TICKETED
                record.updated_at = ticket.updated_at
                tickets.append(ticket)
                document_store.upsert_staging_record(record)
                document_store.upsert_ticket(ticket)
            except Exception:
                record.status = StagingRecordStatus.ERROR
                document_store.upsert_staging_record(record)

    return tickets


def bootstrap_demo(count: int = 50, *, seed: int = 42) -> list[Ticket]:
    reset_demo_store()
    records = seed_staging_records(count=count, seed=seed)
    return diagnose_new_records(records=records, existing_tickets=[])


def staged_record_from_document(document_id: str) -> StagedFailureRecord:
    document = SyntheticRepository().get_document(document_id)
    suffix = document.document_id.split("-")[-1]
    timestamp = datetime(2026, 6, 28, 8, 0, 0)
    return StagedFailureRecord(
        case_id=f"CASE-{suffix}",
        document=document,
        error_logs=[
            ErrorLog(
                error_log_id=f"ERR-{suffix}-01",
                document_id=document.document_id,
                source_system=document.source_system,
                error_code=ERROR_CODES[document.failure_scenario],
                error_text=document.error_message,
                created_at=timestamp,
            )
        ],
        status=StagingRecordStatus.NEW,
        created_at=timestamp,
        updated_at=timestamp,
    )


def bootstrap_golden_document(document_id: str, *, approve: bool = False) -> Ticket:
    """Reset the workbench store and ticket one bundled golden document through the agentic workflow."""
    reset_demo_store()
    record = staged_record_from_document(document_id)
    document_store.upsert_staging_record(record)

    repository = SyntheticRepository()
    workflow = AgenticWorkflow(repository=repository, approval_store=ApprovalStore())
    run = workflow.run(document_id=document_id, approve=approve)
    ticket = create_ticket(record, run)
    record.status = StagingRecordStatus.TICKETED
    record.updated_at = ticket.updated_at
    document_store.upsert_staging_record(record)
    document_store.upsert_ticket(ticket)
    return ticket


def reset_demo_store() -> None:
    from cfin_agents.attachment_store import clear_attachments

    document_store.reset_store()
    clear_attachments()
    for path in (STAGING_FILE, TICKETS_FILE):
        if path.exists():
            path.unlink()


def load_staging_records(path: Path = STAGING_FILE) -> list[StagedFailureRecord]:
    del path
    return document_store.load_staging_records()


def save_staging_records(records: list[StagedFailureRecord], path: Path = STAGING_FILE) -> None:
    del path
    document_store.replace_staging_records(records)


def load_tickets(path: Path = TICKETS_FILE) -> list[Ticket]:
    del path
    return document_store.load_tickets()


def save_tickets(tickets: list[Ticket], path: Path = TICKETS_FILE) -> None:
    del path
    document_store.replace_tickets(tickets)


def clear_ticket_summaries(*, dry_run: bool = False) -> int:
    """Remove persisted agent summaries from all tickets."""
    cleared = 0
    for ticket in load_tickets():
        stored = (ticket.agent_summary or ticket.workflow_run.agent_summary or "").strip()
        if not stored:
            continue
        cleared += 1
        if dry_run:
            continue
        run = ticket.workflow_run.model_copy(update={"agent_summary": None})
        document_store.upsert_ticket(
            ticket.model_copy(
                update={
                    "agent_summary": None,
                    "workflow_run": run,
                }
            )
        )
    return cleared


def refresh_ticket_summaries(*, dry_run: bool = False, clear_first: bool = False) -> int:
    """Regenerate and persist agent summaries for all stored tickets."""
    if clear_first and not dry_run:
        clear_ticket_summaries()

    from cfin_agents.services import generate_analyst_summary

    records_by_case = {record.case_id: record for record in document_store.load_staging_records()}
    tickets = load_tickets()
    updated = 0

    for ticket in tickets:
        record = records_by_case.get(ticket.case_id)
        if not record:
            continue

        run = ticket.workflow_run
        summary = generate_analyst_summary(
            record.document,
            run.diagnosis,
            run.remediation_plan,
            run.governance_decision,
            run.reprocess_result,
        )
        current = (ticket.agent_summary or run.agent_summary or "").strip()
        if summary.strip() == current:
            continue

        updated += 1
        if dry_run:
            continue

        run = run.model_copy(update={"agent_summary": summary})
        document_store.upsert_ticket(
            ticket.model_copy(
                update={
                    "agent_summary": summary,
                    "workflow_run": run,
                }
            )
        )

    return updated


@contextmanager
def _without_openai_summary_calls() -> Iterator[None]:
    original = os.environ.pop("OPENAI_API_KEY", None)
    try:
        yield
    finally:
        if original:
            os.environ["OPENAI_API_KEY"] = original


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed and diagnose synthetic staged failures.")
    parser.add_argument("--count", type=int, default=50, help="Number of staged failures to seed.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic generation seed.")
    parser.add_argument(
        "--inject",
        type=int,
        default=0,
        help="Append fresh NEW staged failures before diagnosis.",
    )
    args = parser.parse_args()

    if args.inject:
        inject_new_records(count=args.inject, seed=args.seed)
        tickets = diagnose_new_records()
    else:
        tickets = bootstrap_demo(count=args.count, seed=args.seed)

    summary = dashboard_summary(tickets)
    print(json.dumps(summary.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
