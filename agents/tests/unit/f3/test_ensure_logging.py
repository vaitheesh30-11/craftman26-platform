"""data_event_ensure_logging — phase-04 §4 Step 1. This is F3's only write
action; gated on `dry_run` (moto CloudTrail backend).
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.f3.ensure_logging import ensure_logging

pytestmark = pytest.mark.unit

_TRAIL_NAME = "org-trail"


def _provisioned_session() -> boto3.Session:
    session = boto3.Session(region_name="us-east-1")
    s3 = session.client("s3")
    s3.create_bucket(Bucket="org-trail-bucket")
    cloudtrail = session.client("cloudtrail")
    cloudtrail.create_trail(Name=_TRAIL_NAME, S3BucketName="org-trail-bucket")
    return session


@mock_aws
def test_already_enabled_reports_true_and_never_writes() -> None:
    session = _provisioned_session()
    cloudtrail = session.client("cloudtrail")
    cloudtrail.put_event_selectors(
        TrailName=_TRAIL_NAME,
        EventSelectors=[
            {
                "ReadWriteType": "All",
                "IncludeManagementEvents": True,
                "DataResources": [{"Type": "AWS::S3::Object", "Values": ["arn:aws:s3:::*/*"]}],
            }
        ],
    )

    result = ensure_logging(
        "111122223333", dry_run=True, trail_name=_TRAIL_NAME, correlation_id="c1", session=session
    )

    assert result == {
        "already_enabled": True,
        "enabled_now": False,
        "trail_arn": f"arn:aws:cloudtrail:us-east-1:123456789012:trail/{_TRAIL_NAME}",
    }


@mock_aws
def test_dry_run_true_reports_disabled_and_does_not_enable() -> None:
    session = _provisioned_session()

    result = ensure_logging(
        "111122223333", dry_run=True, trail_name=_TRAIL_NAME, correlation_id="c2", session=session
    )

    assert result["already_enabled"] is False
    assert result["enabled_now"] is False
    selectors = session.client("cloudtrail").get_event_selectors(TrailName=_TRAIL_NAME)[
        "EventSelectors"
    ]
    assert selectors == []


@mock_aws
def test_dry_run_false_enables_logging_and_preserves_existing_selectors() -> None:
    session = _provisioned_session()
    cloudtrail = session.client("cloudtrail")
    cloudtrail.put_event_selectors(
        TrailName=_TRAIL_NAME,
        EventSelectors=[{"ReadWriteType": "WriteOnly", "IncludeManagementEvents": True}],
    )

    result = ensure_logging(
        "111122223333", dry_run=False, trail_name=_TRAIL_NAME, correlation_id="c3", session=session
    )

    assert result["already_enabled"] is False
    assert result["enabled_now"] is True
    selectors = cloudtrail.get_event_selectors(TrailName=_TRAIL_NAME)["EventSelectors"]
    assert len(selectors) == 2
    assert selectors[0]["ReadWriteType"] == "WriteOnly"
    assert selectors[1]["DataResources"][0]["Values"] == ["arn:aws:s3:::*/*"]
