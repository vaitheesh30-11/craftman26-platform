from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f6.severity import classify_severity

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "action",
    [
        "organizations:deletepolicy",
        "organizations:detachpolicy",
        "cloudtrail:stoplogging",
        "kms:putkeypolicy",
    ],
)
def test_named_critical_actions_are_critical(action: str) -> None:
    assert classify_severity(action, "root") == "CRITICAL"


def test_organizations_list_is_not_critical_even_though_service_matches() -> None:
    assert classify_severity("organizations:listroots", "ou") == "MEDIUM"


def test_iam_write_denied_at_ou_level_is_high() -> None:
    assert classify_severity("iam:deleterole", "ou") == "HIGH"


def test_iam_write_denied_at_root_level_is_medium_not_high() -> None:
    assert classify_severity("iam:deleterole", "root") == "MEDIUM"


def test_unclassified_write_falls_back_to_medium() -> None:
    assert classify_severity("s3:deleteobject", "ou") == "MEDIUM"
