"""E-07 — SCP collision in a 4-level OU chain (phase-13 scenario table).
Real `tools/f7/collision.resolve_collisions` (`walk_scp_chain` ->
`scp_engine.compute_effective_policy` -> `scp_engine.find_collisions`)
against a moto Organizations root -> OU -> nested-OU -> account chain
(one level deeper than `tests/unit/f7/_org_provision.py`'s canonical
3-level fixtures). Passes when: collision detected, plain-English
explanation matches the template `plain_english.build_plain_english`
renders.
"""

from __future__ import annotations

import json

import boto3

from iam_sentinel_agents.tools.f7 import collision


def _provision_four_level_collision(org: boto3.client) -> str:
    org.create_organization(FeatureSet="ALL")
    root_id = org.list_roots()["Roots"][0]["Id"]
    parent_ou_id = org.create_organizational_unit(ParentId=root_id, Name="Platform")[
        "OrganizationalUnit"
    ]["Id"]
    child_ou_id = org.create_organizational_unit(ParentId=parent_ou_id, Name="Workloads")[
        "OrganizationalUnit"
    ]["Id"]
    account_id = org.create_account(Email="fourlevel@example.com", AccountName="fourlevel")[
        "CreateAccountStatus"
    ]["AccountId"]
    org.move_account(
        AccountId=account_id, SourceParentId=root_id, DestinationParentId=child_ou_id
    )

    deny_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "DenyDeleteBucket", "Effect": "Deny", "Action": ["s3:DeleteBucket"], "Resource": "*"}
        ],
    }
    deny_policy_id = org.create_policy(
        Content=json.dumps(deny_doc),
        Description="root deny",
        Name="RootDenyDeleteBucket",
        Type="SERVICE_CONTROL_POLICY",
    )["Policy"]["PolicySummary"]["Id"]
    org.attach_policy(PolicyId=deny_policy_id, TargetId=root_id)

    allow_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "AllowDeleteBucket", "Effect": "Allow", "Action": ["s3:DeleteBucket"], "Resource": "*"}
        ],
    }
    allow_policy_id = org.create_policy(
        Content=json.dumps(allow_doc),
        Description="nested ou allow",
        Name="NestedOuAllowDeleteBucket",
        Type="SERVICE_CONTROL_POLICY",
    )["Policy"]["PolicySummary"]["Id"]
    org.attach_policy(PolicyId=allow_policy_id, TargetId=child_ou_id)

    return account_id


def test_e07_collision_detected_across_a_four_level_ou_chain(moto_session: None) -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = _provision_four_level_collision(org)

    payload = collision.resolve_collisions(account_id, organizations_client=org)

    assert payload.collision_count == 1
    found = payload.collisions[0]
    assert found.action_pattern == "s3:DeleteBucket"
    assert found.denied_at_level == "root"
    assert found.allowed_at_level == "ou"
    assert found.plain_english.startswith(
        "SCP RootDenyDeleteBucket at root level denies s3:DeleteBucket"
    )
    assert found.minimal_fix["strategy"] in {"remove_action_from_list", "condition_exemption"}
    # 4 distinct chain entries: root, the two nested OUs, and the account.
    assert len(payload.scp_chain) == 4
