from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from cfin_agents.eval_results import (  # noqa: E402
    latest_run_records,
    load_summary_eval_records,
    run_summary_eval_batch,
    summarize_records,
)

st.set_page_config(page_title="Eval Results", layout="wide")
st.title("Summary Eval Results")
st.caption(
    "Latest model-graded summary eval runs logged to `evals/model_outputs.jsonl`. "
    "Uses the multi-agent workflow with `gpt-4o-mini` agents/summary and `gpt-4o` judge."
)

records = load_summary_eval_records()
latest = latest_run_records()

if not records:
    st.info("No eval results logged yet. Run a batch below or execute `bash scripts/run_summary_eval_batch.sh`.")
else:
    summary = summarize_records(latest)
    cols = st.columns(4)
    cols[0].metric("Latest run", latest[0].run_id if latest else "—")
    cols[1].metric("Cases", summary["total"])
    cols[2].metric("Passed", summary["passed"])
    cols[3].metric("Pass rate", f"{summary['pass_rate'] * 100:.0f}%")

    rows = [
        {
            "document_id": record.document_id,
            "pass": record.overall_pass,
            "accuracy": record.accuracy_score,
            "actionability": record.actionability_score,
            "execution_mode": record.execution_mode,
            "expected_status": record.expected_status,
            "actual_status": record.actual_status,
            "error": record.error,
        }
        for record in latest
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    selected_doc = st.selectbox(
        "Inspect summary",
        [record.document_id for record in latest],
    )
    selected = next(record for record in latest if record.document_id == selected_doc)
    st.markdown("### Agent summary")
    st.write(selected.agent_summary or "_No summary generated._")
    if selected.judge_reasoning:
        st.markdown("### Judge reasoning")
        st.write(selected.judge_reasoning)
    if selected.error:
        st.error(selected.error)

    with st.expander("All logged runs"):
        st.dataframe(
            [
                {
                    "run_id": record.run_id,
                    "timestamp": record.timestamp,
                    "document_id": record.document_id,
                    "pass": record.overall_pass,
                }
                for record in records
            ],
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.subheader("Run eval batch")

if not os.getenv("OPENAI_API_KEY"):
    st.warning("Set `OPENAI_API_KEY` in `.env` to run live judged evals from the dashboard.")
else:
    st.caption("Runs all 10 golden summary cases. Expect several minutes and API cost.")
    if st.button("Run summary eval batch", type="primary"):
        with st.spinner("Running summary evals for all 10 documents..."):
            run_id, batch_records = run_summary_eval_batch()
            batch_summary = summarize_records(batch_records)
        st.success(
            f"Run `{run_id}` complete: {batch_summary['passed']}/{batch_summary['total']} passed."
        )
        st.rerun()
