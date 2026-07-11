from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from cfin_agents.batch import StagedDocumentRepository
from cfin_agents.document_store import (
    claim_new_staging_records,
    load_tickets,
    staging_counts,
    ticket_count,
    upsert_staging_record,
    upsert_ticket,
)
from cfin_agents.services import ApprovalStore
from cfin_agents.ticket_models import StagingRecordStatus
from cfin_agents.ticketing import create_ticket, dashboard_summary
from cfin_agents.workflow import AgenticWorkflow


def sweep_agentic_batch(
    *,
    batch_size: int = 5,
    approve: bool = False,
    progress_callback=None,
) -> list[dict]:
    pending = claim_new_staging_records(batch_size)
    if not pending:
        return []

    from cfin_agents.document_store import load_staging_records

    repository = StagedDocumentRepository(load_staging_records())
    workflow = AgenticWorkflow(
        repository=repository,
        approval_store=ApprovalStore(),
    )

    results: list[dict] = []
    for record in pending:
        try:
            run = workflow.run(
                document_id=record.document.document_id,
                approve=approve,
            )
            ticket = create_ticket(record, run)
            record.status = StagingRecordStatus.TICKETED
            record.updated_at = ticket.updated_at
            upsert_staging_record(record)
            upsert_ticket(ticket)
            results.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "document_id": ticket.document_id,
                    "reason_code": ticket.reason_code,
                    "assignee": ticket.assignee,
                    "execution_mode": run.execution_mode,
                    "agent_summary": ticket.agent_summary,
                }
            )
        except Exception as exc:
            record.status = StagingRecordStatus.ERROR
            upsert_staging_record(record)
            results.append(
                {
                    "document_id": record.document.document_id,
                    "error": str(exc),
                }
            )
        if progress_callback is not None:
            progress_callback(len(results), len(pending), results[-1])
    return results


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Pick NEW documents from the SQLite queue and run the agentic workflow."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Number of NEW staging documents to process this sweep.",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Record human approval before running each document workflow.",
    )
    args = parser.parse_args()

    results = sweep_agentic_batch(batch_size=args.batch_size, approve=args.approve)
    tickets = load_tickets()
    print(
        json.dumps(
            {
                "processed": len(results),
                "results": results,
                "staging_counts": staging_counts(),
                "ticket_count": ticket_count(),
                "dashboard": dashboard_summary(tickets).model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
