from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from cfin_agents import document_store
from cfin_agents.attachment_store import clear_attachments
from cfin_agents.batch import STAGING_FILE, TICKETS_FILE
from cfin_agents.synthetic_generator import generate_staged_failures


def reset_workbench(*, reseed_count: int | None = 50, seed: int = 42) -> dict[str, int | str]:
    """Clear tickets, staging queue, attachments; optionally seed fresh documents."""
    document_store.reset_store()
    clear_attachments()
    for path in (STAGING_FILE, TICKETS_FILE):
        if path.exists():
            path.unlink()

    seeded = 0
    if reseed_count:
        records = generate_staged_failures(count=reseed_count, seed=seed)
        document_store.replace_staging_records(records)
        seeded = len(records)

    return {
        "seeded_documents": seeded,
        "ticket_count": document_store.ticket_count(),
        "staging_counts": document_store.staging_counts(),
        "database": str(document_store.DB_PATH),
    }


def seed_staging_queue(*, count: int = 50, seed: int = 42, reset: bool = False) -> int:
    if reset:
        reset_workbench(reseed_count=count, seed=seed)
        return count

    records = generate_staged_failures(count=count, seed=seed)
    for record in records:
        document_store.upsert_staging_record(record)
    return len(records)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Seed the SQLite staging queue with synthetic failed documents."
    )
    parser.add_argument("--count", type=int, default=50, help="Documents to generate.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic generation seed.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear tickets, attachments, and staging documents, then seed a fresh queue.",
    )
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Clear tickets, attachments, and staging documents without seeding.",
    )
    args = parser.parse_args()

    if args.clear_only:
        result = reset_workbench(reseed_count=None)
        print(json.dumps(result, indent=2))
        return

    created = seed_staging_queue(count=args.count, seed=args.seed, reset=args.reset)
    print(
        json.dumps(
            {
                "seeded_documents": created,
                "staging_counts": document_store.staging_counts(),
                "ticket_count": document_store.ticket_count(),
                "database": str(document_store.DB_PATH),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
