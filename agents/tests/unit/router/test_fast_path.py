"""Deterministic fast-path mirrors (agents phase-15 §2/§6 Step 2) -- each
mirror composes the same core function its Bedrock-envelope Lambda already
calls, so these tests mostly assert the response shaping (`verdict`/
`reason`/`findings`/`remediation`) and the `AmbiguityError` escalation
contract; the underlying computation itself is already covered by each
feature's own `tools/f{n}` test suite.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.contracts.shadow_guard import ShadowViolation
from iam_sentinel_agents.tools.common import cross_account, fast_path
from iam_sentinel_agents.tools.common.scp_policy_evaluator import LevelPolicies, PolicyRef
from iam_sentinel_agents.tools.f2 import classify as f2_classify
from iam_sentinel_agents.tools.f2.org_tree import OrgContext
from tests.unit.f1._provision import load_fixture, provision
from tests.unit.f7._org_provision import provision_classic_collision, provision_clean_chain

pytestmark = pytest.mark.unit

_ACCOUNT_ID = "123456789012"


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    cross_account.clear_cache_for_tests()
    yield
    cross_account.clear_cache_for_tests()


# --- F1 --------------------------------------------------------------------


@mock_aws
def test_passrole_fast_confirms_a_single_filtered_principal() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    provision(iam, load_fixture("admin_shortcut"))
    session = boto3.Session(region_name="us-east-1")

    result = fast_path.passrole_fast(
        {"account_id": _ACCOUNT_ID, "principal_arn": f"arn:aws:iam::{_ACCOUNT_ID}:user/Deployer"},
        correlation_id="c1",
        session=session,
    )

    assert result["verdict"] == "CONFIRM"
    assert result["findings"]
    assert result["remediation"] is None


@mock_aws
def test_passrole_fast_escalates_when_multiple_principals_are_unfiltered() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    provision(iam, load_fixture("admin_shortcut"))
    session = boto3.Session(region_name="us-east-1")

    with pytest.raises(fast_path.AmbiguityError):
        fast_path.passrole_fast(
            {"account_id": _ACCOUNT_ID}, correlation_id="c1", session=session
        )


@mock_aws
def test_passrole_fast_rejects_when_no_grants_found() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_user(UserName="Bystander")
    session = boto3.Session(region_name="us-east-1")

    result = fast_path.passrole_fast(
        {"account_id": _ACCOUNT_ID, "principal_arn": f"arn:aws:iam::{_ACCOUNT_ID}:user/Bystander"},
        correlation_id="c1",
        session=session,
    )
    assert result["verdict"] == "REJECT"
    assert result["findings"] == []


# --- F4 --------------------------------------------------------------------

_FULL_AWS_ACCESS = PolicyRef(
    arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-FullAWSAccess",
    name="FullAWSAccess",
    document={"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]},
)
_PROPOSED_DENY_TERMINATE = {
    "Version": "2012-10-17",
    "Statement": [
        {"Sid": "DenyTerminate", "Effect": "Deny", "Action": "ec2:TerminateInstances", "Resource": "*"}
    ],
}


def _chain() -> list[dict[str, Any]]:
    return [
        LevelPolicies(level="root", target="r-abcd", policies=[_FULL_AWS_ACCESS]).model_dump(mode="json"),
        LevelPolicies(level="account", target=_ACCOUNT_ID, policies=[]).model_dump(mode="json"),
    ]


def test_scp_impact_fast_confirms_a_blocked_call_with_an_exemption() -> None:
    history = [
        {
            "role_arn": f"arn:aws:iam::{_ACCOUNT_ID}:role/AutoScalerCaller",
            "event_source": "ec2.amazonaws.com",
            "event_name": "TerminateInstances",
            "action": "ec2:TerminateInstances",
            "call_count": 400,
        }
    ]
    result = fast_path.scp_impact_fast(
        {"chain": _chain(), "proposed_scp": _PROPOSED_DENY_TERMINATE, "history": history},
        correlation_id="c1",
    )
    assert result["verdict"] == "CONFIRM"
    assert result["remediation"]["suggested_exemptions"]


def test_scp_impact_fast_rejects_when_nothing_is_blocked() -> None:
    result = fast_path.scp_impact_fast(
        {"chain": _chain(), "proposed_scp": _PROPOSED_DENY_TERMINATE, "history": []},
        correlation_id="c1",
    )
    assert result["verdict"] == "REJECT"
    assert result["findings"] == []


# --- F5 --------------------------------------------------------------------


def _fake_sso_client() -> MagicMock:
    sso = MagicMock()
    sso.list_instances.return_value = {"Instances": [{"InstanceArn": "arn:aws:sso:::instance/i-1"}]}
    sso.describe_permission_set.return_value = {"PermissionSet": {"Name": "EmergencyOps"}}
    accounts_paginator = MagicMock()
    accounts_paginator.paginate.return_value = [{"AccountIds": []}]
    sso.get_paginator.return_value = accounts_paginator
    return sso


@mock_aws
def test_emergency_kill_fast_is_inconclusive_with_no_matching_accounts() -> None:
    result = fast_path.emergency_kill_fast(
        {
            "permission_set_arn": "arn:aws:sso:::permissionSet/i-1/ps-1",
            "ttl_seconds": 900,
            "reason": "compromised key",
            "trigger_source": "manual",
        },
        correlation_id="c1",
        sso_client=_fake_sso_client(),
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["remediation"]["accounts_targeted"] == 0


# --- F7 --------------------------------------------------------------------


@mock_aws
def test_scp_collision_fast_confirms_the_classic_collision() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_classic_collision(org)

    result = fast_path.scp_collision_fast(
        {"account_id": account_id}, correlation_id="c1", session=boto3.Session(region_name="us-east-1")
    )
    assert result["verdict"] == "CONFIRM"
    assert len(result["findings"]) == 1


@mock_aws
def test_scp_collision_fast_rejects_a_clean_chain() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_clean_chain(org)

    result = fast_path.scp_collision_fast(
        {"account_id": account_id}, correlation_id="c1", session=boto3.Session(region_name="us-east-1")
    )
    assert result["verdict"] == "REJECT"


# --- F8 --------------------------------------------------------------------

_SAFE_SCP = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
}
_DENY_ALL_EC2 = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Deny", "Action": "ec2:*", "Resource": "*"}],
}


def _slr_row() -> dict[str, object]:
    return {
        "service_principal": "autoscaling.amazonaws.com",
        "slr_name": "AWSServiceRoleForAutoScaling",
        "required_actions": ["ec2:TerminateInstances", "ec2:RunInstances"],
        "optional_actions": [],
        "core_actions": ["ec2:TerminateInstances"],
        "db_version": "7",
    }


def test_slr_scan_fast_rejects_when_proposed_scp_has_no_conflicts() -> None:
    with patch.object(fast_path.SlrsClient, "list_all", return_value=[_slr_row()]):
        result = fast_path.slr_scan_fast({"proposed_scp": _SAFE_SCP}, correlation_id="c1")
    assert result["verdict"] == "REJECT"
    assert result["findings"] == []


def test_slr_scan_fast_confirms_a_conflict_and_offers_a_safe_scp() -> None:
    with patch.object(fast_path.SlrsClient, "list_all", return_value=[_slr_row()]):
        result = fast_path.slr_scan_fast({"proposed_scp": _DENY_ALL_EC2}, correlation_id="c1")
    assert result["verdict"] == "CONFIRM"
    assert result["remediation"]["safe_scp"]


# --- F2 --------------------------------------------------------------------

_ANALYZER_ARN = "arn:aws:access-analyzer:us-east-1:111122223333:analyzer/org-analyzer"
_ORG = OrgContext(
    org_id="o-a1b2c3d4e5",
    master_account_id="111122223333",
    feature_set="ALL",
    account_ids=["111122223333"],
    ou_paths=["o-a1b2c3d4e5/r-ab12/"],
)


def test_org_context_fast_confirms_a_true_positive() -> None:
    fake_aa = MagicMock()
    fake_aa.get_paginator.return_value.paginate.return_value = [{"findings": [{"id": "f-1"}]}]
    fake_aa.get_finding.return_value = {"finding": {"id": "f-1", "condition": {}}}

    with (
        patch.object(f2_classify, "fetch_org_context", return_value=_ORG),
        patch.object(f2_classify, "_access_analyzer_client", return_value=fake_aa),
    ):
        result = fast_path.org_context_fast(
            {"analyzer_arn": _ANALYZER_ARN},
            correlation_id="c1",
            session=boto3.Session(region_name="us-east-1"),
        )

    assert result["verdict"] == "CONFIRM"
    assert result["findings"][0]["classification"] == "TRUE_POSITIVE"


# --- F3 --------------------------------------------------------------------


class _FakeAthenaClient:
    def start_query_execution(self, **_kwargs: Any) -> dict[str, str]:
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, **_kwargs: Any) -> dict[str, Any]:
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_paginator(self, operation_name: str) -> _FakeAthenaClient:
        assert operation_name == "get_query_results"
        return self

    def paginate(self, **_kwargs: Any) -> list[dict[str, Any]]:
        header = {"Data": [{"VarCharValue": n} for n in ("action", "bucket", "object_key", "call_count")]}
        row = {"Data": [{"VarCharValue": v} for v in ("GetObject", "reports", "a.json", "5")]}
        return [{"ResultSet": {"Rows": [header, row]}}]


def test_data_event_fast_confirms_usage_found() -> None:
    result = fast_path.data_event_fast(
        {"role_arn": f"arn:aws:iam::{_ACCOUNT_ID}:role/DataPipeline"},
        correlation_id="c1",
        athena_client=_FakeAthenaClient(),
    )
    assert result["verdict"] == "CONFIRM"
    assert result["findings"]


# --- F6 (read-only) ----------------------------------------------------------


def _violation() -> ShadowViolation:
    return ShadowViolation(
        action="organizations:deletepolicy",
        principal_arn="arn:aws:iam::111122223333:user/RootOps",
        principal_type="IAMUser",
        would_be_denied_by_scp_arn="arn:aws:organizations::o-1:policy/p-root-deny",
        denying_statement_id="DenyIt",
        would_be_denied_at_level="root",
        event_id="evt-1",
        event_time=datetime(2026, 7, 27, tzinfo=UTC),
        severity="CRITICAL",
    )


def test_shadow_guard_fast_returns_items_and_next_token_shape() -> None:
    fake_findings = MagicMock()
    fake_findings.list_page.return_value = ([{"payload": _violation().model_dump(mode="json")}], None)

    result = fast_path.shadow_guard_fast({"days_back": 7}, findings_client=fake_findings)

    assert result["next_token"] is None
    assert len(result["items"]) == 1
    assert result["items"][0]["action"] == "organizations:deletepolicy"
