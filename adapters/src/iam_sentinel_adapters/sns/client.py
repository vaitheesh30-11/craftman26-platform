"""Thin SNS publish wrapper (phase-01 §3.2 step 6, IAM policy §6:
`sns:Publish` on `SentinelCriticalFindings` only -- no `Subscribe`,
`CreateTopic`, or other topic-management action is ever needed here).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3

from iam_sentinel_adapters.errors import ThrottlingError
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_sns import SNSClient as _BotoSnsClient


class SnsClient:
    def __init__(self, *, topic_arn: str | None = None, client: _BotoSnsClient | None = None) -> None:
        self._topic_arn = topic_arn or settings.critical_findings_topic_arn
        self._client: _BotoSnsClient = client or boto3.client("sns", region_name=settings.region)

    def publish_critical_finding(self, *, subject: str, message: str) -> str:
        response = self._publish(subject=subject[:100], message=message)
        return str(response["MessageId"])

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _publish(self, *, subject: str, message: str) -> dict[str, Any]:
        try:
            return dict(self._client.publish(TopicArn=self._topic_arn, Subject=subject, Message=message))
        except self._client.exceptions.ThrottledException as exc:
            raise ThrottlingError(str(exc)) from exc
