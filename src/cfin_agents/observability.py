from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any


def configure_openai_agents_tracing() -> bool:
    """Patch OpenAI Agents SDK tracing when Langfuse credentials are present."""
    if not _langfuse_enabled():
        return False

    try:
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

        OpenAIAgentsInstrumentor().instrument()
        return True
    except Exception:
        return False


def _langfuse_enabled() -> bool:
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY")
        and os.getenv("LANGFUSE_SECRET_KEY")
        and os.getenv("LANGFUSE_HOST")
    )


@contextlib.contextmanager
def workflow_observation(
    name: str,
    *,
    input_payload: dict[str, Any],
    metadata: dict[str, Any],
    tags: list[str],
    session_id: str,
) -> Iterator[str | None]:
    """Create a Langfuse observation if configured; otherwise no-op."""
    if not _langfuse_enabled():
        yield None
        return

    try:
        from langfuse import get_client

        langfuse = get_client()
        with langfuse.start_as_current_observation(
            name=name,
            input=input_payload,
            metadata=metadata,
        ) as observation:
            observation.update_trace(session_id=session_id, tags=tags)
            trace_id = getattr(observation, "trace_id", None)
            yield trace_id
            langfuse.flush()
    except Exception:
        yield None
