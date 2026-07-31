"""`tools/f7/collision.py` -- both the orchestration function
(`resolve_collisions`) and the `sentinel_handler`-wrapped Bedrock Lambda
envelope, against moto's Organizations mock.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.common import runtime
from iam_sentinel_agents.tools.f7 import collision
from tests.unit.f7._org_provision import (
    provision_classic_collision,
    provision_clean_chain,
    provision_same_level_pair,
)

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

pytestmark = pytest.mark.unit


class _FakeContext:
    aws_request_id = "req-f7-resolve"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


def _fake_context() -> LambdaContext:
    return _FakeContext()  # type: ignore[return-value]


def _event(account_id: str, exclude_statement_ids: list[str] | None = None) -> dict[str, Any]:
    properties = [{"name": "account_id", "type": "string", "value": account_id}]
    if exclude_statement_ids is not None:
        joined = '","'.join(exclude_statement_ids)
        properties.append(
            {"name": "exclude_statement_ids", "type": "array", "value": f'["{joined}"]'}
        )
    return {
        "messageVersion": "1.0",
        "sessionId": "session-f7",
        "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
        "actionGroup": "F7CollisionActions",
        "apiPath": "/resolve",
        "httpMethod": "POST",
        "requestBody": {"content": {"application/json": {"properties": properties}}},
    }


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    runtime.reset_cold_start_tracking_for_tests()


@mock_aws
def test_resolve_collisions_finds_the_classic_root_ou_collision() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_classic_collision(org)

    payload = collision.resolve_collisions(account_id, organizations_client=org)

    assert payload.collision_count == 1
    found = payload.collisions[0]
    assert found.action_pattern == "ec2:RunInstances"
    assert found.denied_at_level == "root"
    assert found.allowed_at_level == "ou"
    assert found.plain_english.startswith(
        "SCP RootDenyRunInstances at root level denies ec2:RunInstances"
    )
    assert found.minimal_fix["strategy"] in {"remove_action_from_list", "condition_exemption"}


@mock_aws
def test_resolve_collisions_clean_chain_has_no_collisions() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_clean_chain(org)

    payload = collision.resolve_collisions(account_id, organizations_client=org)

    assert payload.collision_count == 0
    assert payload.collisions == []


@mock_aws
def test_exclude_statement_ids_mutes_an_acknowledged_collision() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_classic_collision(org)

    payload = collision.resolve_collisions(
        account_id, organizations_client=org, exclude_statement_ids=["DenyRunInstances"]
    )

    assert payload.collision_count == 0


@mock_aws
def test_same_level_allow_deny_pair_is_not_reported_as_a_collision() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_same_level_pair(org)

    payload = collision.resolve_collisions(account_id, organizations_client=org)

    assert payload.collision_count == 0


@mock_aws
def test_lambda_handler_envelope_round_trips_the_payload() -> None:
    import json

    # mock_aws intercepts every boto3 client created inside this context,
    # including the one `resolve_collisions` builds internally when no
    # `organizations_client`/`session` is injected -- so the full
    # production code path (no test-only client) is exercised here.
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_classic_collision(org)

    response = collision.collision_resolve(_event(account_id), _fake_context())

    assert response["response"]["httpStatusCode"] == 200
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body["account_id"] == account_id
    assert body["collision_count"] == 1
    assert body["engine_version"]
