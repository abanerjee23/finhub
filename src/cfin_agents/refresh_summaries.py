from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from cfin_agents.batch import clear_ticket_summaries, refresh_ticket_summaries


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Regenerate agent summaries for tickets already stored in SQLite."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many tickets would change without writing to the database.",
    )
    parser.add_argument(
        "--clear-first",
        action="store_true",
        help="Clear existing summaries from SQLite before regenerating.",
    )
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Clear persisted summaries without regenerating.",
    )
    args = parser.parse_args()

    if args.clear_only:
        cleared = clear_ticket_summaries(dry_run=args.dry_run)
        print(json.dumps({"cleared_tickets": cleared, "dry_run": args.dry_run}, indent=2))
        return

    updated = refresh_ticket_summaries(dry_run=args.dry_run, clear_first=args.clear_first)
    print(
        json.dumps(
            {
                "updated_tickets": updated,
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
