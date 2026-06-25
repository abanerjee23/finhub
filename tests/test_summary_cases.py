from __future__ import annotations

from cfin_agents.eval_cases import load_summary_calibration_cases, load_summary_cases


def test_summary_cases_load_all_ten_documents() -> None:
    cases = load_summary_cases()
    assert len(cases) == 10
    assert {case.document_id for case in cases} == {
        "DOC-1001",
        "DOC-1002",
        "DOC-1003",
        "DOC-1004",
        "DOC-1005",
        "DOC-1006",
        "DOC-1007",
        "DOC-1008",
        "DOC-1009",
        "DOC-1010",
    }


def test_summary_case_golden_fields_are_populated() -> None:
    case = next(case for case in load_summary_cases() if case.document_id == "DOC-1001")
    assert case.golden.expected_action == "create_target_master_data"
    assert case.golden.required_follow_on == "maintain_source_mapping"
    assert case.golden.example_good_summary
    assert case.golden.must_not_say


def test_summary_calibration_cases_load_six_examples() -> None:
    cases = load_summary_calibration_cases()
    assert len(cases) == 6
    assert {case.expected_pass for case in cases} == {True, False}
