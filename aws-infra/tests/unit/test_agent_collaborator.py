"""Loaded via `importlib` -- see `test_agent_settings.py`'s module
docstring for why this can't share a pytest `pythonpath` entry with the
other `functions/*/handler.py` modules.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HANDLER_PATH = (
    Path(__file__).resolve().parents[2] / "functions" / "agent_collaborator" / "handler.py"
)
_spec = importlib.util.spec_from_file_location("agent_collaborator_handler", _HANDLER_PATH)
assert _spec is not None and _spec.loader is not None
collaborator_handler = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = collaborator_handler
_spec.loader.exec_module(collaborator_handler)


@pytest.fixture(autouse=True)
def _mock_bedrock_agent() -> MagicMock:
    with patch.object(collaborator_handler, "_bedrock_agent") as mock:
        yield mock


def test_create_associates_against_draft_version(_mock_bedrock_agent: MagicMock) -> None:
    _mock_bedrock_agent.associate_agent_collaborator.return_value = {
        "agentCollaborator": {"collaboratorId": "collab-1"}
    }

    result = collaborator_handler.route_request(
        "Create",
        {
            "SupervisorAgentId": "prime-agent-id",
            "CollaboratorName": "F1PassRoleCartographer",
            "CollaborationInstruction": "Delegate PassRole graph questions to F1.",
            "CollaboratorAliasArn": "arn:aws:bedrock:us-east-1:111111111111:agent-alias/f1-agent/dev",
        },
        physical_id=None,
    )

    assert result["PhysicalResourceId"] == "collab-1"
    _mock_bedrock_agent.associate_agent_collaborator.assert_called_once_with(
        agentId="prime-agent-id",
        agentVersion="DRAFT",
        collaboratorName="F1PassRoleCartographer",
        collaborationInstruction="Delegate PassRole graph questions to F1.",
        agentDescriptor={"aliasArn": "arn:aws:bedrock:us-east-1:111111111111:agent-alias/f1-agent/dev"},
        relayConversationHistory="TO_COLLABORATOR",
    )


def test_delete_disassociates(_mock_bedrock_agent: MagicMock) -> None:
    result = collaborator_handler.route_request(
        "Delete", {"SupervisorAgentId": "prime-agent-id"}, physical_id="collab-1"
    )

    _mock_bedrock_agent.disassociate_agent_collaborator.assert_called_once_with(
        agentId="prime-agent-id", agentVersion="DRAFT", collaboratorId="collab-1"
    )
    assert result["PhysicalResourceId"] == "collab-1"


def test_delete_without_physical_id_is_a_noop(_mock_bedrock_agent: MagicMock) -> None:
    result = collaborator_handler.route_request(
        "Delete", {"SupervisorAgentId": "prime-agent-id"}, physical_id=None
    )

    _mock_bedrock_agent.disassociate_agent_collaborator.assert_not_called()
    assert result["PhysicalResourceId"] == "already-deleted"


def test_update_without_physical_id_raises(_mock_bedrock_agent: MagicMock) -> None:
    with pytest.raises(ValueError, match="physical resource id"):
        collaborator_handler.route_request(
            "Update", {"SupervisorAgentId": "prime-agent-id"}, physical_id=None
        )


def test_unsupported_request_type_raises(_mock_bedrock_agent: MagicMock) -> None:
    with pytest.raises(ValueError, match="unsupported RequestType"):
        collaborator_handler.route_request(
            "Replace", {"SupervisorAgentId": "prime-agent-id"}, physical_id="collab-1"
        )
