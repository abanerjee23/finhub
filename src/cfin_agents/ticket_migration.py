from __future__ import annotations

from typing import Any

from cfin_agents.ticket_models import OperatorStatus

_LEGACY_TO_OPERATOR: dict[str, str] = {
    "received": OperatorStatus.ASSIGNED.value,
    "diagnosed": OperatorStatus.ASSIGNED.value,
    "assigned": OperatorStatus.ASSIGNED.value,
    "in_progress": OperatorStatus.IN_PROGRESS.value,
    "resolved": OperatorStatus.RESOLVED.value,
    "blocked": OperatorStatus.BLOCKED.value,
}


def migrate_ticket_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy ticket JSON blobs loaded from SQLite."""
    if "operator_status" in raw:
        return raw

    legacy_status = str(raw.pop("status", OperatorStatus.ASSIGNED.value))
    raw["operator_status"] = _LEGACY_TO_OPERATOR.get(legacy_status, OperatorStatus.ASSIGNED.value)

    raw.pop("is_pending_approval", None)
    raw.pop("is_blocked", None)
    raw.pop("policy_status", None)
    return raw
