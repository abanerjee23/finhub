from __future__ import annotations

from pathlib import Path

from cfin_agents.eval_results import (
    SummaryEvalRecord,
    append_summary_eval_record,
    latest_run_records,
    load_summary_eval_records,
    summarize_records,
)


def test_summary_eval_record_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "model_outputs.jsonl"
    record = SummaryEvalRecord(
        run_id="eval-test",
        timestamp="2026-06-25T09:00:00+00:00",
        case_id="summary-doc-1002",
        document_id="DOC-1002",
        execution_mode="openai_agents_sdk_guarded",
        expected_status="reprocessed",
        actual_status="reprocessed",
        overall_pass=True,
        accuracy_score=5,
        actionability_score=5,
        agent_summary="Example summary",
    )
    append_summary_eval_record(record, path=path)
    loaded = load_summary_eval_records(path=path)
    assert len(loaded) == 1
    assert loaded[0].document_id == "DOC-1002"
    assert latest_run_records(path=path)[0].overall_pass is True


def test_summarize_records_counts_pass_fail() -> None:
    records = [
        SummaryEvalRecord(
            run_id="r1",
            timestamp="t",
            case_id="a",
            document_id="DOC-1001",
            execution_mode="x",
            expected_status="needs_approval",
            actual_status="needs_approval",
            overall_pass=True,
        ),
        SummaryEvalRecord(
            run_id="r1",
            timestamp="t",
            case_id="b",
            document_id="DOC-1002",
            execution_mode="x",
            expected_status="reprocessed",
            actual_status="reprocessed",
            overall_pass=False,
        ),
    ]
    summary = summarize_records(records)
    assert summary == {"total": 2, "passed": 1, "failed": 1, "pass_rate": 0.5}
