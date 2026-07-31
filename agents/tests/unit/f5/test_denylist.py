"""Denylist pattern matching (phase-06 §9 acceptance: "Denylist enforced
in unit tests with 5 adversarial fixtures").
"""

from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f5.denylist import is_denylisted

pytestmark = pytest.mark.unit

_PATTERNS = [
    "arn:aws:iam::*:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_SentinelOperator_*",
    "arn:aws:iam::*:role/SentinelCrossAccountRole",
]


@pytest.mark.parametrize(
    "role_arn",
    [
        "arn:aws:iam::111122223333:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_SentinelOperator_abc123",
        "arn:aws:iam::444455556666:role/SentinelCrossAccountRole",
        "arn:aws:iam::777788889999:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_SentinelOperator_xyz",
    ],
)
def test_protected_roles_are_denylisted(role_arn: str) -> None:
    assert is_denylisted(role_arn, _PATTERNS) is True


@pytest.mark.parametrize(
    "role_arn",
    [
        "arn:aws:iam::111122223333:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_ReadOnlyOps_abc123",
        "arn:aws:iam::444455556666:role/CompletelyUnrelatedRole",
    ],
)
def test_ordinary_sso_roles_are_not_denylisted(role_arn: str) -> None:
    assert is_denylisted(role_arn, _PATTERNS) is False
