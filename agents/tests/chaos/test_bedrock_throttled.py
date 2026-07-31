"""Chaos: Bedrock throttled (phase-13 §4 Step 4). Real `BedrockProvider.
_invoke_agent` retry wrapping (`Policy.AGGRESSIVE`: 5 retries, 6 attempts
total) against a fake `bedrock-agent-runtime` client that always raises
`ThrottlingException`. Passes when: exactly 6 attempts are made, and the
failure propagates as `ThrottlingError` rather than a fabricated success
-- the conservative-default outcome phase-13's Objective demands.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.errors import ThrottlingError
from iam_sentinel_adapters.llm.bedrock_provider import BedrockProvider


class _FakeThrottlingError(Exception):
    pass


def _always_throttling_agent_runtime() -> MagicMock:
    client = MagicMock()
    client.exceptions.ThrottlingException = _FakeThrottlingError
    client.invoke_agent.side_effect = _FakeThrottlingError("rate exceeded")
    return client


def test_invoke_agent_retries_six_times_then_raises_throttling_error() -> None:
    agent_runtime = _always_throttling_agent_runtime()
    provider = BedrockProvider(
        agent_runtime_client=agent_runtime,
        runtime_client=MagicMock(),
        cost_meter=MagicMock(),
        guardrail=MagicMock(),
    )

    with pytest.raises(ThrottlingError):
        provider.invoke_agent(
            agent_id="prime-agent",
            alias_id="dev",
            session_id="01JBP2VHF9K3Q0Z8R7X6M5N4C1",
            input_text="audit passrole",
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4C1",
        )

    # Policy.AGGRESSIVE: max_retries=5 -> stop_after_attempt(6). The
    # conservative-default assertion phase-13's Objective names directly:
    # `retry(..., reraise=True)` guarantees the last exception always
    # propagates -- there is no code path that catches `ThrottlingError`
    # after retry exhaustion and fabricates a `BedrockAgentResponse`.
    assert agent_runtime.invoke_agent.call_count == 6
