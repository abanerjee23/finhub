from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cfin_agents.services import ApprovalStore  # noqa: E402
from cfin_agents.workflow import AgenticWorkflow  # noqa: E402

st.set_page_config(
    page_title="Agentic CFIN Workflow",
    page_icon="",
    layout="wide",
)


def get_workflow() -> AgenticWorkflow:
    if "approval_store" not in st.session_state:
        st.session_state.approval_store = ApprovalStore()
    if "workflow" not in st.session_state:
        st.session_state.workflow = AgenticWorkflow(approval_store=st.session_state.approval_store)
    return st.session_state.workflow


workflow = get_workflow()
documents = workflow.list_documents()

st.title("FinHub - Agentic Document Resolution Workbench")
st.caption(
    "Synthetic Central Finance-style failed document replication with deterministic guardrails, "
    "optional OpenAI Agents SDK orchestration, Langfuse traces, and Railway-ready deployment."
)

with st.sidebar:
    st.header("Run Controls")
    document_ids = [document.document_id for document in documents]
    selected_document_id = st.selectbox("Failed document", document_ids)
    force_deterministic = st.toggle(
        "Force deterministic mode",
        value=os.getenv("DISABLE_LLM", "0").lower() in {"1", "true", "yes"},
        help="Run without model calls. Guardrails are deterministic in both modes.",
    )
    approve = st.toggle(
        "Record human approval before run",
        value=False,
        help="Use for approval-gated remediation scenarios.",
    )
    run_clicked = st.button("Run guarded workflow", type="primary")

selected_document = workflow.deterministic.repository.get_document(selected_document_id)
context = workflow.toolset.document_context(selected_document_id)

queue_rows = [
    {
        "document_id": document.document_id,
        "source_system": document.source_system,
        "failure_scenario": document.failure_scenario,
        "amount": document.amount,
        "currency": document.currency,
    }
    for document in documents
]

st.subheader("Failed Document Queue")
st.dataframe(queue_rows, use_container_width=True, hide_index=True)

left, right = st.columns([1, 1])

with left:
    st.subheader("Selected Document")
    st.json(selected_document.model_dump(mode="json"))

with right:
    st.subheader("Validation Context")
    st.json(
        {
            "validation_issues": context["validation_issues"],
            "mappings": context["mappings"],
        }
    )

if run_clicked:
    with st.spinner("Running governed agent workflow..."):
        st.session_state.latest_run = workflow.run(
            selected_document_id,
            approve=approve,
            force_deterministic=force_deterministic,
        )

if "latest_run" in st.session_state:
    run = st.session_state.latest_run
    st.divider()
    st.subheader("Workflow Result")

    metric_cols = st.columns(4)
    metric_cols[0].metric("Status", run.status)
    metric_cols[1].metric("Execution Mode", run.execution_mode)
    metric_cols[2].metric("Reason Code", run.diagnosis.reason_code)
    metric_cols[3].metric(
        "Reprocessed",
        "Yes" if run.reprocess_result and run.reprocess_result.success else "No",
    )

    result_cols = st.columns([1, 1, 1])
    with result_cols[0]:
        st.markdown("### Diagnosis")
        st.json(run.diagnosis.model_dump(mode="json"))
    with result_cols[1]:
        st.markdown("### Remediation Plan")
        st.json(run.remediation_plan.model_dump(mode="json"))
    with result_cols[2]:
        st.markdown("### Governance Decision")
        st.json(run.governance_decision.model_dump(mode="json"))

    if run.reprocess_result:
        st.markdown("### Reprocessing")
        st.json(run.reprocess_result.model_dump(mode="json"))

    if run.agent_summary:
        st.markdown("### Agent Summary")
        st.write(run.agent_summary)

    if run.langfuse_trace_id:
        st.info(f"Langfuse trace ID: `{run.langfuse_trace_id}`")
    else:
        st.caption(
            "Langfuse trace ID unavailable. Configure Langfuse environment variables "
            "to export traces."
        )

    st.markdown("### Audit Timeline")
    st.dataframe(
        [
            {
                "timestamp": event.timestamp.isoformat(),
                "actor": event.actor,
                "action": event.action,
                "details": event.details,
            }
            for event in run.audit_events
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Select a failed document and run the guarded workflow.")
