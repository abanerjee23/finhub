from __future__ import annotations

from cfin_agents.observability import (
    langfuse_enabled,
    langfuse_host,
    langfuse_trace_url,
    summary_generation_observation,
)


def test_langfuse_host_reads_base_url(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com/")
    assert langfuse_host() == "https://cloud.langfuse.com"


def test_langfuse_trace_url(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    assert langfuse_trace_url("trace-abc123") is None

    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    assert langfuse_trace_url("trace-abc123") == "https://cloud.langfuse.com/trace/trace-abc123"


def test_langfuse_enabled_with_base_url(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    assert langfuse_enabled() is True


def test_summary_generation_observation_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    with summary_generation_observation(
        model="gpt-4o",
        input_payload={"messages": []},
    ) as observation:
        assert observation is None


def test_summary_generation_observation_creates_generation(monkeypatch) -> None:
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    mock_obs = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_obs)
    mock_cm.__exit__ = MagicMock(return_value=False)

    mock_client = MagicMock()
    mock_client.start_as_current_observation.return_value = mock_cm

    with patch("cfin_agents.observability.ensure_langfuse_env"), patch(
        "langfuse.get_client", return_value=mock_client
    ):
        with summary_generation_observation(
            model="gpt-4o",
            input_payload={"messages": [{"role": "user", "content": "hello"}]},
            model_parameters={"temperature": 0.2, "max_tokens": 160},
        ) as observation:
            assert observation is mock_obs

    mock_client.start_as_current_observation.assert_called_once()
    call_kwargs = mock_client.start_as_current_observation.call_args.kwargs
    assert call_kwargs["as_type"] == "generation"
    assert call_kwargs["name"] == "analyst-summary"
    assert call_kwargs["model"] == "gpt-4o"
