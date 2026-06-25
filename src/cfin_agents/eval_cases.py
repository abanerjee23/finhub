from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from cfin_agents.models import WorkflowRun

CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "deterministic_cases.yaml"
SUMMARY_CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "summary_cases.yaml"
SUMMARY_CALIBRATION_CASES_PATH = (
    Path(__file__).resolve().parents[2] / "evals" / "summary_calibration_cases.yaml"
)


class AuditExpectation(BaseModel):
    must_include: list[dict[str, str]] = Field(default_factory=list)
    must_exclude: list[dict[str, str]] = Field(default_factory=list)


class ExpectedOutcome(BaseModel):
    status: str
    failure_scenario: str
    reason_code: str
    action: str
    requires_approval: bool
    allowed: bool
    reprocessed: bool


class DeterministicCase(BaseModel):
    id: str
    description: str
    document_id: str
    approve: bool = False
    expected: ExpectedOutcome
    audit: AuditExpectation | None = None


def load_deterministic_cases(path: Path = CASES_PATH) -> list[DeterministicCase]:
    with path.open(encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    return [DeterministicCase.model_validate(item) for item in raw["cases"]]


class SummaryGoldenExpectations(BaseModel):
    approval_required: bool
    expected_status: str
    expected_reason_code: str
    expected_action: str
    required_follow_on: str
    root_cause_expected: str
    must_mention: list[str] = Field(default_factory=list)
    must_not_say: list[str] = Field(default_factory=list)
    example_good_summary: str


class SummaryCase(BaseModel):
    id: str
    description: str
    document_id: str
    approve: bool = False
    golden: SummaryGoldenExpectations


def load_summary_cases(path: Path = SUMMARY_CASES_PATH) -> list[SummaryCase]:
    with path.open(encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    return [SummaryCase.model_validate(item) for item in raw["cases"]]


class SummaryCalibrationCase(BaseModel):
    id: str
    document_id: str
    summary_case_id: str
    expected_pass: bool
    generated_summary: str


def load_summary_calibration_cases(
    path: Path = SUMMARY_CALIBRATION_CASES_PATH,
) -> list[SummaryCalibrationCase]:
    with path.open(encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    return [SummaryCalibrationCase.model_validate(item) for item in raw["cases"]]


def workflow_summary(run: WorkflowRun) -> dict[str, Any]:
    summary = run.promptfoo_summary()
    return {key: str(value) if hasattr(value, "value") else value for key, value in summary.items()}


def assert_case_outcome(run: WorkflowRun, case: DeterministicCase) -> dict[str, bool]:
    actual = workflow_summary(run)
    expected = case.expected
    return {
        "status": actual["status"] == expected.status,
        "failure_scenario": actual["failure_scenario"] == expected.failure_scenario,
        "reason_code": actual["reason_code"] == expected.reason_code,
        "action": actual["action"] == expected.action,
        "requires_approval": actual["requires_approval"] is expected.requires_approval,
        "allowed": actual["allowed"] is expected.allowed,
        "reprocessed": actual["reprocessed"] is expected.reprocessed,
    }


def assert_audit_trail(run: WorkflowRun, case: DeterministicCase) -> dict[str, bool]:
    if case.audit is None:
        return {}

    events = [{"actor": event.actor, "action": event.action} for event in run.audit_events]
    checks: dict[str, bool] = {}

    for index, required in enumerate(case.audit.must_include):
        checks[f"must_include_{index}"] = required in events

    for index, forbidden in enumerate(case.audit.must_exclude):
        checks[f"must_exclude_{index}"] = forbidden not in events

    return checks


def evaluate_case(
    run: WorkflowRun, case: DeterministicCase
) -> tuple[bool, dict[str, bool], dict[str, Any]]:
    outcome_checks = assert_case_outcome(run, case)
    audit_checks = assert_audit_trail(run, case)
    all_checks = {**outcome_checks, **audit_checks}
    passed = all(all_checks.values())
    return passed, all_checks, workflow_summary(run)
