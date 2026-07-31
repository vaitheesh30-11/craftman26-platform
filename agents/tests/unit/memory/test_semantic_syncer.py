"""`memory_semantic_syncer` (phase-14 §5 Step4 / §7 Test Plan: "syncer
change-detection -- no write on unchanged body"; idempotent on repeat
runs).
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.memory import semantic_syncer
from tests.unit.memory import _ddb

pytestmark = pytest.mark.unit


@mock_aws
def test_sync_accounts_writes_one_entity_per_account_and_emits_changed() -> None:
    memory = _ddb.memory_client()
    org = boto3.client("organizations", region_name="us-east-1")
    org.create_organization(FeatureSet="ALL")

    changed_events: list[tuple[str, str]] = []
    summary = semantic_syncer.sync_accounts(
        memory, org, emit_changed=lambda kind, key: changed_events.append((kind, key))
    )

    assert summary["scanned"] == 1
    assert summary["changed"] == 1
    assert len(changed_events) == 1
    assert changed_events[0][0] == "account"


@mock_aws
def test_sync_accounts_second_run_with_unchanged_state_writes_nothing() -> None:
    memory = _ddb.memory_client()
    org = boto3.client("organizations", region_name="us-east-1")
    org.create_organization(FeatureSet="ALL")

    changed_events: list[tuple[str, str]] = []
    semantic_syncer.sync_accounts(memory, org, emit_changed=lambda k, e: changed_events.append((k, e)))
    second = semantic_syncer.sync_accounts(
        memory, org, emit_changed=lambda k, e: changed_events.append((k, e))
    )

    assert second["scanned"] == 1
    assert second["changed"] == 0
    assert len(changed_events) == 1  # only the first run's write emitted a change


@mock_aws
def test_sync_permission_sets_writes_one_entity_per_permission_set() -> None:
    memory = _ddb.memory_client()
    sso = boto3.client("sso-admin", region_name="us-east-1")
    instance_arn = sso.list_instances()["Instances"][0]["InstanceArn"]
    sso.create_permission_set(Name="AdminAccess", InstanceArn=instance_arn)

    summary = semantic_syncer.sync_permission_sets(memory, sso, instance_arn=instance_arn)

    assert summary["scanned"] == 1
    assert summary["changed"] == 1


@mock_aws
def test_run_syncer_totals_across_wired_in_sub_syncers() -> None:
    memory = _ddb.memory_client()
    org = boto3.client("organizations", region_name="us-east-1")
    org.create_organization(FeatureSet="ALL")
    sso = boto3.client("sso-admin", region_name="us-east-1")
    instance_arn = sso.list_instances()["Instances"][0]["InstanceArn"]
    sso.create_permission_set(Name="ReadOnly", InstanceArn=instance_arn)

    summary = semantic_syncer.run_syncer(
        memory, org_client=org, sso_client=sso, sso_instance_arn=instance_arn
    )

    assert summary["scanned"] == 2
    assert summary["changed"] == 2


@mock_aws
def test_run_syncer_is_a_no_op_with_no_clients_wired_in() -> None:
    memory = _ddb.memory_client()
    summary = semantic_syncer.run_syncer(memory, org_client=None)
    assert summary["scanned"] == 0
    assert summary["changed"] == 0
