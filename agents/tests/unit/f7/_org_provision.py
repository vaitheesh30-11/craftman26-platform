"""Provisions a moto-mocked AWS Organizations root -> OU -> account chain
with attached SCPs (phase-08 §8's "canonical fixtures"). Not a test module
itself (leading underscore keeps pytest from collecting it).
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_organizations.client import OrganizationsClient


def provision_classic_collision(org: OrganizationsClient) -> str:
    """Root denies ec2:RunInstances explicitly; the OU explicitly allows it.
    Deny wins -- exactly one collision expected.
    """
    org.create_organization(FeatureSet="ALL")
    root_id = org.list_roots()["Roots"][0]["Id"]
    ou_id = org.create_organizational_unit(ParentId=root_id, Name="Workloads")[
        "OrganizationalUnit"
    ]["Id"]
    account_id = org.create_account(Email="classic@example.com", AccountName="classic")[
        "CreateAccountStatus"
    ]["AccountId"]
    org.move_account(AccountId=account_id, SourceParentId=root_id, DestinationParentId=ou_id)

    deny_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyRunInstances",
                "Effect": "Deny",
                "Action": ["ec2:RunInstances"],
                "Resource": "*",
            }
        ],
    }
    deny_policy_id = org.create_policy(
        Content=json.dumps(deny_doc),
        Description="root deny",
        Name="RootDenyRunInstances",
        Type="SERVICE_CONTROL_POLICY",
    )["Policy"]["PolicySummary"]["Id"]
    org.attach_policy(PolicyId=deny_policy_id, TargetId=root_id)

    allow_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowRunInstances",
                "Effect": "Allow",
                "Action": ["ec2:RunInstances"],
                "Resource": "*",
            }
        ],
    }
    allow_policy_id = org.create_policy(
        Content=json.dumps(allow_doc),
        Description="ou allow",
        Name="OuAllowRunInstances",
        Type="SERVICE_CONTROL_POLICY",
    )["Policy"]["PolicySummary"]["Id"]
    org.attach_policy(PolicyId=allow_policy_id, TargetId=ou_id)

    return account_id


def provision_clean_chain(org: OrganizationsClient) -> str:
    """Only the default FullAWSAccess SCP is attached anywhere -- zero
    collisions, effective policy is fully open.
    """
    org.create_organization(FeatureSet="ALL")
    root_id = org.list_roots()["Roots"][0]["Id"]
    account_id = org.create_account(Email="clean@example.com", AccountName="clean")[
        "CreateAccountStatus"
    ]["AccountId"]
    org.move_account(AccountId=account_id, SourceParentId=root_id, DestinationParentId=root_id)
    return account_id


def provision_same_level_pair(org: OrganizationsClient) -> str:
    """Allow and Deny for the same action both attached at the OU level --
    not a cross-level collision per phase-08 §4 Step 3's own wording.
    """
    org.create_organization(FeatureSet="ALL")
    root_id = org.list_roots()["Roots"][0]["Id"]
    ou_id = org.create_organizational_unit(ParentId=root_id, Name="SameLevel")[
        "OrganizationalUnit"
    ]["Id"]
    account_id = org.create_account(Email="sl@example.com", AccountName="samelevel")[
        "CreateAccountStatus"
    ]["AccountId"]
    org.move_account(AccountId=account_id, SourceParentId=root_id, DestinationParentId=ou_id)

    allow_doc: dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowCreateUser",
                "Effect": "Allow",
                "Action": ["iam:CreateUser"],
                "Resource": "*",
            }
        ],
    }
    deny_doc: dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyCreateUser",
                "Effect": "Deny",
                "Action": ["iam:CreateUser"],
                "Resource": "*",
            }
        ],
    }
    for doc, name in ((allow_doc, "OuAllowCreateUser"), (deny_doc, "OuDenyCreateUser")):
        policy_id = org.create_policy(
            Content=json.dumps(doc), Description="d", Name=name, Type="SERVICE_CONTROL_POLICY"
        )["Policy"]["PolicySummary"]["Id"]
        org.attach_policy(PolicyId=policy_id, TargetId=ou_id)

    return account_id
