from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Coerce naive datetimes (legacy payloads) to UTC-aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


UTCDateTime = Annotated[datetime, AfterValidator(ensure_utc)]
