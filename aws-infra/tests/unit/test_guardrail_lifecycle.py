from __future__ import annotations

from unittest.mock import MagicMock, patch

import handler as guardrail_handler
import pytest


@pytest.fixture(autouse=True)
def _mock_bedrock() -> MagicMock:
    with patch.object(guardrail_handler, "_bedrock") as mock:
        yield mock


def test_create_publishes_a_guardrail_version(_mock_bedrock: MagicMock) -> None:
    _mock_bedrock.create_guardrail.return_value = {
        "guardrailId": "gr-123",
        "guardrailArn": "arn:aws:bedrock:us-east-1:111111111111:guardrail/gr-123",
    }
    _mock_bedrock.create_guardrail_version.return_value = {"version": "1"}

    result = guardrail_handler.route_request(
        "Create",
        {
            "GuardrailName": "IAMSentinelGuardrail-dev",
            "BlockedInputMessaging": "blocked-in",
            "BlockedOutputsMessaging": "blocked-out",
        },
        physical_id=None,
    )

    assert result["PhysicalResourceId"] == "gr-123"
    assert result["Data"]["GuardrailVersion"] == "1"
    _mock_bedrock.create_guardrail_version.assert_called_once_with(guardrailIdentifier="gr-123")


def test_update_bumps_a_new_version_without_deleting_the_prior_one(_mock_bedrock: MagicMock) -> None:
    _mock_bedrock.create_guardrail_version.return_value = {"version": "2"}

    result = guardrail_handler.route_request(
        "Update",
        {
            "GuardrailName": "IAMSentinelGuardrail-dev",
            "BlockedInputMessaging": "blocked-in",
            "BlockedOutputsMessaging": "blocked-out",
        },
        physical_id="gr-123",
    )

    assert result["Data"]["GuardrailVersion"] == "2"
    _mock_bedrock.delete_guardrail.assert_not_called()


def test_update_without_physical_id_raises(_mock_bedrock: MagicMock) -> None:
    with pytest.raises(ValueError, match="physical resource id"):
        guardrail_handler.route_request("Update", {}, physical_id=None)


def test_delete_calls_delete_guardrail(_mock_bedrock: MagicMock) -> None:
    result = guardrail_handler.route_request("Delete", {}, physical_id="gr-123")

    _mock_bedrock.delete_guardrail.assert_called_once_with(guardrailIdentifier="gr-123")
    assert result["PhysicalResourceId"] == "gr-123"


def test_delete_without_physical_id_is_a_noop(_mock_bedrock: MagicMock) -> None:
    result = guardrail_handler.route_request("Delete", {}, physical_id=None)

    _mock_bedrock.delete_guardrail.assert_not_called()
    assert result["PhysicalResourceId"] == "already-deleted"


def test_unsupported_request_type_raises(_mock_bedrock: MagicMock) -> None:
    with pytest.raises(ValueError, match="unsupported RequestType"):
        guardrail_handler.route_request("Replace", {}, physical_id="gr-123")
