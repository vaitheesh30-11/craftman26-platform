"""Role-privilege classification rubric (phase-02 §3.3)."""

from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f1.privilege import classify_role_privilege

pytestmark = pytest.mark.unit


def test_administrator_access_by_managed_policy_name() -> None:
    result = classify_role_privilege(
        attached_policy_arns=["arn:aws:iam::aws:policy/AdministratorAccess"], statements=[]
    )
    assert result == "AdministratorAccess"


def test_administrator_access_by_equivalent_statement() -> None:
    statements = [{"Effect": "Allow", "Action": "*", "Resource": "*"}]
    assert classify_role_privilege(attached_policy_arns=[], statements=statements) == "AdministratorAccess"


def test_power_user_access_by_managed_policy_name() -> None:
    result = classify_role_privilege(
        attached_policy_arns=["arn:aws:iam::aws:policy/PowerUserAccess"], statements=[]
    )
    assert result == "PowerUserAccess"


def test_iam_write_action() -> None:
    statements = [{"Effect": "Allow", "Action": ["iam:CreatePolicy"], "Resource": "*"}]
    assert classify_role_privilege(attached_policy_arns=[], statements=statements) == "IAMWrite"


def test_create_role_is_iam_write() -> None:
    statements = [{"Effect": "Allow", "Action": "iam:CreateRole", "Resource": "*"}]
    assert classify_role_privilege(attached_policy_arns=[], statements=statements) == "IAMWrite"


def test_sensitive_service_kms() -> None:
    statements = [{"Effect": "Allow", "Action": "kms:Decrypt", "Resource": "*"}]
    assert classify_role_privilege(attached_policy_arns=[], statements=statements) == "SensitiveService"


def test_sensitive_service_broad_assume_role() -> None:
    statements = [{"Effect": "Allow", "Action": "sts:AssumeRole", "Resource": "*"}]
    assert classify_role_privilege(attached_policy_arns=[], statements=statements) == "SensitiveService"


def test_other_for_contained_permissions() -> None:
    statements = [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::bucket/*"}]
    assert classify_role_privilege(attached_policy_arns=[], statements=statements) == "Other"


def test_deny_statements_are_ignored() -> None:
    statements = [{"Effect": "Deny", "Action": "*", "Resource": "*"}]
    assert classify_role_privilege(attached_policy_arns=[], statements=statements) == "Other"


def test_no_statements_and_no_policies_is_other() -> None:
    assert classify_role_privilege(attached_policy_arns=[], statements=[]) == "Other"
