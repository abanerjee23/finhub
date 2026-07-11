from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from dotenv import load_dotenv

from cfin_agents.models import WorkflowRun, WorkflowStatus
from cfin_agents.observability import configure_openai_agents_tracing, workflow_observation
from cfin_agents.paths import runtime_data_dir
from cfin_agents.repository import SyntheticRepository
from cfin_agents.services import ApprovalStore, DeterministicWorkflow
from cfin_agents.timeutil import utc_now
from cfin_agents.toolkit import FinanceToolset

load_dotenv()


class AgenticWorkflow:
    """Workflow facade with optional OpenAI Agents SDK orchestration."""

    def __init__(
        self,
        repository: SyntheticRepository | None = None,
        approval_store: ApprovalStore | None = None,
    ) -> None:
        self.approval_store = approval_store or ApprovalStore()
        self.deterministic = DeterministicWorkflow(
            repository=repository,
            approval_store=self.approval_store,
        )
        self.toolset = FinanceToolset(self.deterministic)
        self.tracing_enabled = configure_openai_agents_tracing()

    def list_documents(self):
        return self.deterministic.repository.list_documents()

    def run(self, document_id: str, approve: bool = False, force_deterministic: bool = False):
        with workflow_observation(
            "agentic-cfin-workflow",
            input_payload={"document_id": document_id, "approve": approve},
            metadata={"prototype": "agentic-cfin", "domain": "central-finance-simulation"},
            tags=["cfin", "agentic-workflow"],
            session_id=f"document-{document_id}",
        ) as trace_id:
            if self._should_use_llm(force_deterministic):
                run = _run_sync(self._run_with_agents(document_id, approve))
            else:
                run = self.deterministic.run(
                    document_id=document_id,
                    approve=approve,
                    execution_mode="deterministic_guarded",
                )

            run.langfuse_trace_id = trace_id
            return run

    def _should_use_llm(self, force_deterministic: bool) -> bool:
        if force_deterministic:
            return False
        if os.getenv("DISABLE_LLM", "").lower() in {"1", "true", "yes"}:
            return False
        return bool(os.getenv("OPENAI_API_KEY"))

    async def _run_with_agents(self, document_id: str, approve: bool) -> WorkflowRun:
        try:
            from agents import Agent, ModelSettings, Runner, function_tool
        except Exception:
            return self.deterministic.run(
                document_id=document_id,
                approve=approve,
                execution_mode="deterministic_guarded",
            )

        toolset = self.toolset

        @function_tool
        def get_document_context(document_id: str) -> dict[str, Any]:
            """Return source document, target validation issues, and master-data mappings."""
            return toolset.document_context(document_id)

        @function_tool
        def classify_failure(document_id: str) -> dict[str, Any]:
            """Classify the failed finance document and return evidence."""
            return toolset.classify_failure(document_id)

        @function_tool
        def propose_remediation(document_id: str) -> dict[str, Any]:
            """Create a remediation plan with risk and approval requirements."""
            return toolset.propose_remediation(document_id)

        @function_tool
        def evaluate_governance(document_id: str) -> dict[str, Any]:
            """Evaluate deterministic policy guardrails for the proposed action."""
            return toolset.evaluate_governance(document_id)

        @function_tool
        def controlled_reprocess(document_id: str) -> dict[str, Any]:
            """Reprocess only when deterministic governance permits execution."""
            return toolset.controlled_reprocess(document_id)

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        settings = (
            ModelSettings()
            if model.startswith("gpt-5")
            else ModelSettings(temperature=0)
        )

        intake_agent = Agent(
            name="CFIN Intake Agent",
            instructions=(
                "Gather the synthetic source document, target validation issues, and available "
                "mappings. Do not infer missing master data."
            ),
            model=model,
            model_settings=settings,
            tools=[get_document_context],
        )
        diagnosis_agent = Agent(
            name="CFIN Diagnosis Agent",
            instructions="Classify the root cause using the provided deterministic classifier.",
            model=model,
            model_settings=settings,
            tools=[classify_failure],
        )
        remediation_agent = Agent(
            name="CFIN Remediation Planner",
            instructions="Propose a remediation plan and identify whether approval is required.",
            model=model,
            model_settings=settings,
            tools=[propose_remediation],
        )
        governance_agent = Agent(
            name="CFIN Governance Agent",
            instructions=(
                "Enforce policy using the deterministic governance tool. Never override a blocked "
                "or approval-required decision."
            ),
            model=model,
            model_settings=settings,
            tools=[evaluate_governance, controlled_reprocess],
        )
        manager = Agent(
            name="CFIN Workflow Manager",
            instructions=(
                "Coordinate failed document remediation in this order: intake, diagnosis, "
                "remediation planning, governance evaluation, then controlled reprocessing only "
                "if allowed. Return a concise audit summary."
            ),
            model=model,
            model_settings=settings,
            tools=[
                intake_agent.as_tool(
                    tool_name="intake_document",
                    tool_description="Collect document and validation context.",
                ),
                diagnosis_agent.as_tool(
                    tool_name="diagnose_document",
                    tool_description="Diagnose document replication failure.",
                ),
                remediation_agent.as_tool(
                    tool_name="plan_remediation",
                    tool_description="Plan remediation and identify risk.",
                ),
                governance_agent.as_tool(
                    tool_name="govern_and_reprocess",
                    tool_description="Evaluate guardrails and reprocess only if permitted.",
                ),
            ],
        )

        if approve:
            self.approval_store.approve(document_id)

        prompt = (
            f"Run the safe CFIN workflow for document {document_id}. "
            f"Human approval already recorded: {approve}. "
            "Respect deterministic tool outputs as the source of truth."
        )
        agent_final_output: str | None = None
        try:
            agent_result = await Runner.run(manager, prompt)
            if agent_result.final_output is not None:
                agent_final_output = str(agent_result.final_output)
        except Exception:
            agent_final_output = None

        # The deterministic controller is the authoritative final state, even when agents run.
        # agent_summary comes from generate_analyst_summary() (SUMMARY_MODEL, default gpt-4o).
        run = self.deterministic.run(
            document_id=document_id,
            approve=False,
            execution_mode="openai_agents_sdk_guarded",
        )
        run.agent_final_output = agent_final_output
        run.shadow_agreement = _shadow_agreement(run.status, agent_final_output)
        _log_shadow_record(run)
        return run


# Keyword cues per deterministic status, used to score whether the shadow-mode
# agent narrative agrees with the authoritative outcome.
_SHADOW_STATUS_CUES: dict[WorkflowStatus, tuple[str, ...]] = {
    WorkflowStatus.REPROCESSED: ("reprocess", "posted", "resolved"),
    WorkflowStatus.NEEDS_APPROVAL: ("approval", "approve", "sign-off"),
    WorkflowStatus.BLOCKED: ("block", "closed period", "cannot", "not allowed"),
    WorkflowStatus.DIAGNOSED: ("diagnos",),
    WorkflowStatus.NEW: (),
}


def _shadow_agreement(status: WorkflowStatus, agent_output: str | None) -> bool | None:
    if not agent_output:
        return None
    lowered = agent_output.lower()
    cues = _SHADOW_STATUS_CUES.get(status, ())
    return any(cue in lowered for cue in cues)


def _log_shadow_record(run: WorkflowRun) -> None:
    """Append a shadow-mode comparison record for offline eval analysis."""
    try:
        log_path = runtime_data_dir() / "agent_shadow_log.jsonl"
        record = {
            "timestamp": utc_now().isoformat(),
            "document_id": run.document_id,
            "deterministic_status": run.status.value,
            "shadow_agreement": run.shadow_agreement,
            "agent_final_output": run.agent_final_output,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass


def run_document_workflow(
    document_id: str,
    approve: bool = False,
    force_deterministic: bool = False,
) -> WorkflowRun:
    return AgenticWorkflow().run(
        document_id=document_id,
        approve=approve,
        force_deterministic=force_deterministic,
    )


def _run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()
