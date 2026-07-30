"""Loaded via `importlib` rather than a shared pytest `pythonpath` entry:
`guardrail_lifecycle/handler.py` (already on `pythonpath`) and
`agent_collaborator/handler.py` (this same phase) both also define a
top-level `handler.py` -- adding all three to `pythonpath` would make
`import handler` resolve to whichever module Python cached first, per the
same collision `test_athena_bootstrap.py` (aws-infra phase-03) already
worked around.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HANDLER_PATH = (
    Path(__file__).resolve().parents[2] / "functions" / "agent_settings" / "handler.py"
)
_spec = importlib.util.spec_from_file_location("agent_settings_handler", _HANDLER_PATH)
assert _spec is not None and _spec.loader is not None
agent_settings_handler = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = agent_settings_handler
_spec.loader.exec_module(agent_settings_handler)


@pytest.fixture(autouse=True)
def _mock_bedrock_agent() -> MagicMock:
    with patch.object(agent_settings_handler, "_bedrock_agent") as mock:
        yield mock


def test_create_calls_update_agent_with_collaboration_and_memory(
    _mock_bedrock_agent: MagicMock,
) -> None:
    result = agent_settings_handler.route_request(
        "Create",
        {
            "AgentId": "agent-123",
            "AgentName": "SentinelPrime",
            "AgentResourceRoleArn": "arn:aws:iam::111111111111:role/SentinelPrimeRole",
            "FoundationModel": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "Instruction": "You are Sentinel Prime.",
            "AgentCollaboration": "SUPERVISOR",
            "MemoryConfiguration": {"enabledMemoryTypes": ["SESSION_SUMMARY"], "storageDays": 30},
        },
        physical_id=None,
    )

    assert result["PhysicalResourceId"] == "agent-123"
    _mock_bedrock_agent.update_agent.assert_called_once_with(
        agentId="agent-123",
        agentName="SentinelPrime",
        agentResourceRoleArn="arn:aws:iam::111111111111:role/SentinelPrimeRole",
        foundationModel="anthropic.claude-3-5-sonnet-20241022-v2:0",
        instruction="You are Sentinel Prime.",
        agentCollaboration="SUPERVISOR",
        memoryConfiguration={"enabledMemoryTypes": ["SESSION_SUMMARY"], "storageDays": 30},
    )


def test_update_omits_unset_optional_fields(_mock_bedrock_agent: MagicMock) -> None:
    agent_settings_handler.route_request(
        "Update",
        {
            "AgentId": "agent-123",
            "AgentName": "SentinelF1",
            "AgentResourceRoleArn": "arn:aws:iam::111111111111:role/SentinelF1Role",
            "FoundationModel": "anthropic.claude-3-5-haiku-20241022-v1:0",
            "Instruction": "You are F1.",
        },
        physical_id="agent-123",
    )

    called_kwargs = _mock_bedrock_agent.update_agent.call_args.kwargs
    assert "agentCollaboration" not in called_kwargs
    assert "memoryConfiguration" not in called_kwargs


def test_delete_is_a_noop(_mock_bedrock_agent: MagicMock) -> None:
    result = agent_settings_handler.route_request("Delete", {}, physical_id="agent-123")

    _mock_bedrock_agent.update_agent.assert_not_called()
    assert result["PhysicalResourceId"] == "agent-123"


def test_unsupported_request_type_raises(_mock_bedrock_agent: MagicMock) -> None:
    with pytest.raises(ValueError, match="unsupported RequestType"):
        agent_settings_handler.route_request("Replace", {}, physical_id="agent-123")
