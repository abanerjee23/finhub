from __future__ import annotations

import random
from datetime import datetime, timedelta

from cfin_agents.models import FailureScenario, FinancialDocument
from cfin_agents.repository import SyntheticRepository
from cfin_agents.ticket_models import ErrorLog, StagedFailureRecord, StagingRecordStatus
from cfin_agents.timeutil import utc_now

SCENARIO_WEIGHTS: dict[FailureScenario, int] = {
    FailureScenario.COST_CENTER_SOURCE_MAPPING_MISSING: 18,
    FailureScenario.GL_SOURCE_MAPPING_MISSING: 16,
    FailureScenario.PROFIT_CENTER_SOURCE_MAPPING_MISSING: 14,
    FailureScenario.MISSING_VENDOR: 12,
    FailureScenario.MISSING_CUSTOMER: 10,
    FailureScenario.MISSING_COST_CENTER_MASTER: 9,
    FailureScenario.MISSING_GL_ACCOUNT_MASTER: 8,
    FailureScenario.MISSING_PROFIT_CENTER_MASTER: 6,
    FailureScenario.CLOSED_POSTING_PERIOD: 5,
    FailureScenario.MISSING_ASSET_MASTER: 2,
}

ERROR_CODES: dict[FailureScenario, str] = {
    FailureScenario.GL_SOURCE_MAPPING_MISSING: "AIF_MP_GL_001",
    FailureScenario.COST_CENTER_SOURCE_MAPPING_MISSING: "AIF_MP_CC_001",
    FailureScenario.PROFIT_CENTER_SOURCE_MAPPING_MISSING: "AIF_MP_PC_001",
    FailureScenario.MISSING_GL_ACCOUNT_MASTER: "AIF_MD_GL_001",
    FailureScenario.MISSING_COST_CENTER_MASTER: "AIF_MD_CC_001",
    FailureScenario.MISSING_PROFIT_CENTER_MASTER: "AIF_MD_PC_001",
    FailureScenario.MISSING_VENDOR: "AIF_MD_VENDOR_001",
    FailureScenario.MISSING_CUSTOMER: "AIF_MD_CUSTOMER_001",
    FailureScenario.MISSING_ASSET_MASTER: "AIF_MD_ASSET_001",
    FailureScenario.CLOSED_POSTING_PERIOD: "AIF_DC_PERIOD_001",
}

SOURCE_SYSTEMS = ("ERP-NA", "ERP-EU", "ERP-APAC", "ERP-LATAM")
COMPANY_CODES = ("1000", "2000", "3000", "4000")
CURRENCIES = ("USD", "EUR", "BRL")


def generate_staged_failures(
    count: int = 50,
    *,
    seed: int = 42,
    start_index: int = 1,
    created_at: datetime | None = None,
) -> list[StagedFailureRecord]:
    """Generate a deterministic staging queue of new failed documents and AIF-style logs."""
    rng = random.Random(seed)
    repository = SyntheticRepository()
    seed_documents = repository.list_documents()
    documents_by_scenario = {document.failure_scenario: document for document in seed_documents}
    scenarios = list(SCENARIO_WEIGHTS)
    weights = [SCENARIO_WEIGHTS[scenario] for scenario in scenarios]
    base_time = created_at or utc_now()

    records: list[StagedFailureRecord] = []
    for offset in range(count):
        index = start_index + offset
        scenario = rng.choices(scenarios, weights=weights, k=1)[0]
        template = documents_by_scenario[scenario]
        document = _document_from_template(template, index, rng)
        timestamp = base_time + timedelta(minutes=offset * 3)
        case_id = f"CASE-{index:05d}"
        records.append(
            StagedFailureRecord(
                case_id=case_id,
                document=document,
                error_logs=[
                    ErrorLog(
                        error_log_id=f"ERR-{index:05d}-01",
                        document_id=document.document_id,
                        source_system=document.source_system,
                        error_code=ERROR_CODES[scenario],
                        error_text=document.error_message,
                        created_at=timestamp,
                    )
                ],
                status=StagingRecordStatus.NEW,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    return records


def _document_from_template(
    template: FinancialDocument,
    index: int,
    rng: random.Random,
) -> FinancialDocument:
    source_system = rng.choice(SOURCE_SYSTEMS)
    company_code = rng.choice(COMPANY_CODES)
    currency = rng.choice(CURRENCIES)
    amount = round(rng.uniform(1_500, 28_000), 2)
    if template.failure_scenario == FailureScenario.CLOSED_POSTING_PERIOD:
        posting_date = "2026-04-30"
    else:
        posting_date = (datetime(2026, 5, 1) + timedelta(days=index % 45)).date().isoformat()

    return template.model_copy(
        update={
            "document_id": f"DOC-GEN-{index:05d}",
            "source_system": source_system,
            "source_document_ref": f"{source_system.split('-')[-1]}-{900000 + index}",
            "company_code": company_code,
            "amount": amount,
            "currency": currency,
            "posting_date": posting_date,
            "error_message": _error_message(template, index),
        }
    )


def _error_message(template: FinancialDocument, index: int) -> str:
    base = template.error_message.rstrip(".")
    return f"{base}. AIF staging batch detected failure instance {index:05d}."
