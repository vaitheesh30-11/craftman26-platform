from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_adapters.errors import GuardrailInterventionError
from iam_sentinel_adapters.llm.bedrock_provider import BedrockProvider


class _ThrottlingException(Exception):
    pass


def _make_provider() -> tuple[BedrockProvider, MagicMock, MagicMock, MagicMock, MagicMock]:
    agent_runtime = MagicMock()
    agent_runtime.exceptions.ThrottlingException = _ThrottlingException
    runtime = MagicMock()
    runtime.exceptions.ThrottlingException = _ThrottlingException
    cost_meter = MagicMock()
    cost_meter.projected.return_value = 0.0
    guardrail = MagicMock()
    guardrail.guardrail_id.return_value = "gr-1"
    guardrail.guardrail_version.return_value = "1"

    provider = BedrockProvider(
        agent_runtime_client=agent_runtime,
        runtime_client=runtime,
        cost_meter=cost_meter,
        guardrail=guardrail,
    )
    return provider, agent_runtime, runtime, cost_meter, guardrail


def test_invoke_agent_returns_completion() -> None:
    provider, agent_runtime, _, _, _ = _make_provider()
    agent_runtime.invoke_agent.return_value = {
        "completion": [{"chunk": {"bytes": b"hello "}}, {"chunk": {"bytes": b"world"}}]
    }

    response = provider.invoke_agent(
        agent_id="a1", alias_id="al1", session_id="s1", input_text="hi", correlation_id="corr-1"
    )

    assert response.completion == "hello world"


def test_invoke_agent_raises_on_guardrail_intervention() -> None:
    provider, agent_runtime, _, _, _ = _make_provider()
    agent_runtime.invoke_agent.return_value = {
        "completion": [{"chunk": {"bytes": b"blocked"}}],
        "stopReason": "guardrail_intervened",
    }

    with pytest.raises(GuardrailInterventionError):
        provider.invoke_agent(
            agent_id="a1", alias_id="al1", session_id="s1", input_text="hi", correlation_id="corr-1"
        )


def test_invoke_agent_retries_then_succeeds_on_throttling() -> None:
    provider, agent_runtime, _, _, _ = _make_provider()
    agent_runtime.invoke_agent.side_effect = [
        _ThrottlingException("throttled"),
        {"completion": [{"chunk": {"bytes": b"ok"}}]},
    ]

    response = provider.invoke_agent(
        agent_id="a1", alias_id="al1", session_id="s1", input_text="hi", correlation_id="corr-1"
    )

    assert response.completion == "ok"
    assert agent_runtime.invoke_agent.call_count == 2


def test_invoke_model_returns_text() -> None:
    provider, _, runtime, _, _ = _make_provider()
    runtime.converse.return_value = {
        "output": {"message": {"content": [{"text": "the answer"}]}},
        "usage": {"totalTokens": 42},
    }

    result = provider.invoke_model(messages=[{"role": "user", "content": "question"}], correlation_id="corr-1")

    assert result == "the answer"


def test_retrieve_maps_chunks() -> None:
    provider, agent_runtime, _, _, _ = _make_provider()
    agent_runtime.retrieve.return_value = {
        "retrievalResults": [
            {
                "content": {"text": "chunk text"},
                "location": {"s3Location": {"uri": "s3://bucket/key"}},
                "score": 0.9,
            }
        ]
    }

    chunks = provider.retrieve(knowledge_base_id="kb-1", query="q", correlation_id="corr-1")

    assert len(chunks) == 1
    assert chunks[0].content == "chunk text"
    assert chunks[0].source == "s3://bucket/key"
