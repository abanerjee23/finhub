from __future__ import annotations

import base64
import contextlib
import os
from collections.abc import Iterator
from typing import Any

_tracing_configured = False


def langfuse_host() -> str | None:
    """Return Langfuse base URL from LANGFUSE_HOST or LANGFUSE_BASE_URL."""
    host = (os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "").strip().rstrip("/")
    return host or None


def langfuse_enabled() -> bool:
    return bool(
        langfuse_host()
        and os.getenv("LANGFUSE_PUBLIC_KEY")
        and os.getenv("LANGFUSE_SECRET_KEY")
    )


def langfuse_trace_url(trace_id: str | None) -> str | None:
    host = langfuse_host()
    if not host or not trace_id:
        return None
    return f"{host}/trace/{trace_id}"


def langfuse_status() -> dict[str, Any]:
    if not langfuse_enabled():
        return {"enabled": False}
    try:
        ensure_langfuse_env()
        from langfuse import get_client

        client = get_client()
        connected = client.auth_check()
        return {
            "enabled": True,
            "connected": connected,
            "host": langfuse_host(),
        }
    except Exception as exc:
        return {
            "enabled": True,
            "connected": False,
            "host": langfuse_host(),
            "error": str(exc),
        }


def ensure_langfuse_env() -> None:
    """Normalize Langfuse + OTEL exporter env vars for SDK and OpenInference."""
    host = langfuse_host()
    if not host:
        return

    os.environ.setdefault("LANGFUSE_HOST", host)
    os.environ.setdefault("LANGFUSE_BASE_URL", host)

    public = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret = os.getenv("LANGFUSE_SECRET_KEY", "")
    auth = base64.b64encode(f"{public}:{secret}".encode()).decode()
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", f"{host}/api/public/otel")
    os.environ.setdefault(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"Authorization=Basic {auth}",
    )


def configure_openai_agents_tracing() -> bool:
    """Send OpenAI Agents SDK spans to Langfuse via OpenInference + OTLP."""
    global _tracing_configured
    if not langfuse_enabled():
        return False
    if _tracing_configured:
        return True

    try:
        ensure_langfuse_env()

        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        existing = trace.get_tracer_provider()
        if isinstance(existing, TracerProvider):
            tracer_provider = existing
        else:
            tracer_provider = TracerProvider()
            trace.set_tracer_provider(tracer_provider)

        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        OpenAIAgentsInstrumentor().instrument(tracer_provider=tracer_provider)
        _tracing_configured = True
        return True
    except Exception:
        return False


@contextlib.contextmanager
def workflow_observation(
    name: str,
    *,
    input_payload: dict[str, Any],
    metadata: dict[str, Any],
    tags: list[str],
    session_id: str,
) -> Iterator[str | None]:
    """Create a Langfuse root observation if configured; otherwise no-op."""
    if not langfuse_enabled():
        yield None
        return

    try:
        ensure_langfuse_env()
        from langfuse import get_client, propagate_attributes

        langfuse = get_client()
        with propagate_attributes(session_id=session_id, tags=tags, trace_name=name):
            with langfuse.start_as_current_observation(
                as_type="span",
                name=name,
                input=input_payload,
                metadata=metadata,
            ) as observation:
                trace_id = getattr(observation, "trace_id", None)
                yield trace_id
                langfuse.flush()
    except Exception:
        yield None


@contextlib.contextmanager
def summary_generation_observation(
    *,
    model: str,
    input_payload: dict[str, Any],
    model_parameters: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Create a Langfuse generation observation for analyst summary LLM calls."""
    if not langfuse_enabled():
        yield None
        return

    try:
        ensure_langfuse_env()
        from langfuse import get_client

        langfuse = get_client()
        with langfuse.start_as_current_observation(
            as_type="generation",
            name="analyst-summary",
            model=model,
            input=input_payload,
            model_parameters=model_parameters,
            metadata={"purpose": "analyst-facing-summary"},
        ) as observation:
            yield observation
    except Exception:
        yield None
