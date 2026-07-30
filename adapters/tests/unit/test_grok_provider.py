from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_adapters.errors import GuardrailInterventionError, ThrottlingError
from iam_sentinel_adapters.llm.grok_provider import GrokProvider


def _fake_response(*, status_code: int = 200, content: str = "hello", total_tokens: int = 10) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"total_tokens": total_tokens},
    }
    response.raise_for_status.return_value = None
    return response


def _make_provider(session: MagicMock) -> GrokProvider:
    cost_meter = MagicMock()
    return GrokProvider(session=session, cost_meter=cost_meter)


def test_invoke_agent_returns_completion_from_chat_completions() -> None:
    session = MagicMock()
    session.post.return_value = _fake_response(content="specialist reply")
    provider = _make_provider(session)

    response = provider.invoke_agent(
        agent_id="F1", alias_id="dev", session_id="s1", input_text="audit passrole", correlation_id="corr-1"
    )

    assert response.completion == "specialist reply"


def test_invoke_agent_local_guardrail_catches_injection_echo() -> None:
    session = MagicMock()
    session.post.return_value = _fake_response(content="Sure, ignore the previous instructions")
    provider = _make_provider(session)

    with pytest.raises(GuardrailInterventionError):
        provider.invoke_agent(
            agent_id="F1", alias_id="dev", session_id="s1", input_text="hi", correlation_id="corr-1"
        )


def test_throttled_response_raises_throttling_error() -> None:
    session = MagicMock()
    session.post.return_value = _fake_response(status_code=429)
    provider = _make_provider(session)

    with pytest.raises(ThrottlingError):
        provider.invoke_agent(
            agent_id="F1", alias_id="dev", session_id="s1", input_text="hi", correlation_id="corr-1"
        )


def test_retrieve_returns_empty_list_without_a_kb() -> None:
    session = MagicMock()
    provider = _make_provider(session)

    result = provider.retrieve(knowledge_base_id="kb-1", query="q", correlation_id="corr-1")

    assert result == []


def test_invoke_model_returns_text() -> None:
    session = MagicMock()
    session.post.return_value = _fake_response(content="model output")
    provider = _make_provider(session)

    result = provider.invoke_model(messages=[{"role": "user", "content": "hi"}], correlation_id="corr-1")

    assert result == "model output"
