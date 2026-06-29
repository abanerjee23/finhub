from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from cfin_agents.paths import runtime_data_dir
from cfin_agents.ticket_migration import migrate_ticket_payload
from cfin_agents.ticket_models import StagedFailureRecord, StagingRecordStatus, Ticket

DB_PATH = runtime_data_dir() / "finhub.db"


def init_db(path: Path | None = None) -> None:
    database = path or DB_PATH
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database))
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS staging_documents (
                case_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_staging_status_created
                ON staging_documents(status, created_at);
            """
        )
        connection.commit()
    finally:
        connection.close()


def reset_store(*, path: Path | None = None) -> None:
    init_db(path)
    with _connect(path) as connection:
        connection.execute("DELETE FROM staging_documents")
        connection.execute("DELETE FROM tickets")
        connection.commit()


def staging_counts(*, path: Path | None = None) -> dict[str, int]:
    init_db(path)
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) FROM staging_documents GROUP BY status"
        ).fetchall()
    return {status: count for status, count in rows}


def replace_staging_records(
    records: list[StagedFailureRecord],
    *,
    path: Path | None = None,
) -> None:
    init_db(path)
    with _connect(path) as connection:
        connection.execute("DELETE FROM staging_documents")
        for record in records:
            _insert_staging_record(connection, record)
        connection.commit()


def upsert_staging_record(record: StagedFailureRecord, *, path: Path | None = None) -> None:
    init_db(path)
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO staging_documents (case_id, document_id, status, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                document_id = excluded.document_id,
                status = excluded.status,
                payload = excluded.payload,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            _staging_row(record),
        )
        connection.commit()


def load_staging_records(*, path: Path | None = None) -> list[StagedFailureRecord]:
    init_db(path)
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT payload FROM staging_documents
            ORDER BY created_at ASC, case_id ASC
            """
        ).fetchall()
    return [_record_from_payload(row[0]) for row in rows]


def claim_new_staging_records(
    limit: int,
    *,
    path: Path | None = None,
) -> list[StagedFailureRecord]:
    init_db(path)
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT payload FROM staging_documents
            WHERE status = ?
            ORDER BY created_at ASC, case_id ASC
            LIMIT ?
            """,
            (StagingRecordStatus.NEW.value, limit),
        ).fetchall()
    return [_record_from_payload(row[0]) for row in rows]


def load_tickets(*, path: Path | None = None) -> list[Ticket]:
    init_db(path)
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT payload FROM tickets
            ORDER BY created_at ASC, ticket_id ASC
            """
        ).fetchall()
    return [_ticket_from_payload(row[0]) for row in rows]


def _ticket_from_payload(payload: str) -> Ticket:
    data = migrate_ticket_payload(json.loads(payload))
    return Ticket.model_validate(data)


def get_ticket(ticket_id: str, *, path: Path | None = None) -> Ticket | None:
    init_db(path)
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT payload FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
    return _ticket_from_payload(row[0]) if row else None


def upsert_ticket(ticket: Ticket, *, path: Path | None = None) -> None:
    init_db(path)
    payload = ticket.model_dump_json()
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO tickets (ticket_id, case_id, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                case_id = excluded.case_id,
                payload = excluded.payload,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                ticket.ticket_id,
                ticket.case_id,
                payload,
                ticket.created_at.isoformat(),
                ticket.updated_at.isoformat(),
            ),
        )
        connection.commit()


def replace_tickets(tickets: list[Ticket], *, path: Path | None = None) -> None:
    init_db(path)
    with _connect(path) as connection:
        connection.execute("DELETE FROM tickets")
        for ticket in tickets:
            connection.execute(
                """
                INSERT INTO tickets (ticket_id, case_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ticket.ticket_id,
                    ticket.case_id,
                    ticket.model_dump_json(),
                    ticket.created_at.isoformat(),
                    ticket.updated_at.isoformat(),
                ),
            )
        connection.commit()


def ticket_count(*, path: Path | None = None) -> int:
    init_db(path)
    with _connect(path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM tickets").fetchone()
    return int(row[0]) if row else 0


def _insert_staging_record(connection: sqlite3.Connection, record: StagedFailureRecord) -> None:
    connection.execute(
        """
        INSERT INTO staging_documents (case_id, document_id, status, payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        _staging_row(record),
    )


def _staging_row(record: StagedFailureRecord) -> tuple[str, str, str, str, str, str]:
    return (
        record.case_id,
        record.document.document_id,
        record.status.value,
        record.model_dump_json(),
        record.created_at.isoformat(),
        record.updated_at.isoformat(),
    )


def _record_from_payload(payload: str) -> StagedFailureRecord:
    return StagedFailureRecord.model_validate_json(payload)


@contextmanager
def _connect(path: Path | None = None):
    database = path or DB_PATH
    connection = sqlite3.connect(str(database))
    try:
        yield connection
    finally:
        connection.close()
