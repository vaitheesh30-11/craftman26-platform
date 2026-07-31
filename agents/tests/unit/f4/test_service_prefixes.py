from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.common.service_prefixes import canonicalize_action, is_write_action

pytestmark = pytest.mark.unit


def test_canonicalize_action_strips_the_amazonaws_com_suffix() -> None:
    assert canonicalize_action("s3.amazonaws.com", "PutBucketPolicy") == "s3:PutBucketPolicy"


def test_canonicalize_action_maps_a_diverging_event_source() -> None:
    assert (
        canonicalize_action("monitoring.amazonaws.com", "PutMetricAlarm")
        == "cloudwatch:PutMetricAlarm"
    )


@pytest.mark.parametrize(
    "event_name",
    ["PutObject", "CreateRole", "DeleteBucket", "AttachRolePolicy", "ModifyInstanceAttribute"],
)
def test_write_verb_prefixes_are_classified_as_writes(event_name: str) -> None:
    assert is_write_action(event_name) is True


@pytest.mark.parametrize(
    "event_name", ["GetObject", "ListRoles", "DescribeInstances", "HeadBucket"]
)
def test_read_verb_prefixes_are_not_classified_as_writes(event_name: str) -> None:
    assert is_write_action(event_name) is False
