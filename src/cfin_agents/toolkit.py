from __future__ import annotations

from typing import Any

from cfin_agents.models import FinancialDocument
from cfin_agents.services import DeterministicWorkflow


class FinanceToolset:
    """Deterministic tool surface that agents are allowed to use."""

    def __init__(self, workflow: DeterministicWorkflow) -> None:
        self.workflow = workflow

    def document_context(self, document_id: str) -> dict[str, Any]:
        document = self.workflow.repository.get_document(document_id)
        validation_issues = self.workflow.validator.validate(document)
        mappings = {
            "gl_account": [
                mapping.model_dump()
                for mapping in self.workflow.repository.find_mappings(
                    "gl_account", document.gl_account
                )
            ],
            "profit_center": [
                mapping.model_dump()
                for mapping in self.workflow.repository.find_mappings(
                    "profit_center", document.profit_center
                )
            ],
            "cost_center": [
                mapping.model_dump()
                for mapping in self.workflow.repository.find_mappings(
                    "cost_center", document.cost_center
                )
            ],
            "business_partner": [
                mapping.model_dump()
                for mapping in self.workflow.repository.find_mappings(
                    "business_partner", document.business_partner
                )
            ],
        }
        return {
            "document": document.model_dump(),
            "validation_issues": [issue.model_dump() for issue in validation_issues],
            "mappings": mappings,
        }

    def classify_failure(self, document_id: str) -> dict[str, Any]:
        document = self.workflow.repository.get_document(document_id)
        diagnosis = self.workflow.diagnosis_service.diagnose(document)
        return diagnosis.model_dump(mode="json")

    def propose_remediation(self, document_id: str) -> dict[str, Any]:
        document = self.workflow.repository.get_document(document_id)
        diagnosis = self.workflow.diagnosis_service.diagnose(document)
        plan = self.workflow.planner.plan(document, diagnosis)
        return plan.model_dump(mode="json")

    def evaluate_governance(self, document_id: str) -> dict[str, Any]:
        document = self.workflow.repository.get_document(document_id)
        diagnosis = self.workflow.diagnosis_service.diagnose(document)
        plan = self.workflow.planner.plan(document, diagnosis)
        decision = self.workflow.policy.evaluate(document, plan, diagnosis)
        return decision.model_dump(mode="json")

    def controlled_reprocess(self, document_id: str) -> dict[str, Any]:
        document = self.workflow.repository.get_document(document_id)
        diagnosis = self.workflow.diagnosis_service.diagnose(document)
        plan = self.workflow.planner.plan(document, diagnosis)
        decision = self.workflow.policy.evaluate(document, plan, diagnosis)
        result = self.workflow.reprocessor.execute(document, plan, decision)
        return result.model_dump(mode="json")

    @staticmethod
    def compact_document(document: FinancialDocument) -> str:
        return (
            f"{document.document_id} from {document.source_system}, amount "
            f"{document.amount:,.2f} {document.currency}, failure={document.failure_scenario}"
        )
