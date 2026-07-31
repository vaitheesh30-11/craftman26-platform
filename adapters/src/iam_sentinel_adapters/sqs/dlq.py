"""`sqs:GetQueueAttributes` wrapper for DLQ depth reads (backend phase-04
§2/§4 step 2 -- `GET /operations/health`). Which queue URLs count as "every
DLQ" is settings-driven, not discovered (see `AdapterSettings.dlq_queue_urls`
and ADR 0023) -- this client only knows how to read the depth of a queue URL
it is given.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import NonRetryableError, ThrottlingError
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_cloudwatch import CloudWatchClient
    from mypy_boto3_sqs import SQSClient

_THROTTLE_CODES = {"ThrottlingException", "RequestThrottled"}


def _queue_name(queue_url: str) -> str:
    return urlparse(queue_url).path.rsplit("/", maxsplit=1)[-1]


class DlqClient:
    def __init__(
        self,
        *,
        sqs_client: SQSClient | None = None,
        cloudwatch_client: CloudWatchClient | None = None,
    ) -> None:
        self._sqs: SQSClient = sqs_client or boto3.client("sqs", region_name=settings.region)
        self._cloudwatch: CloudWatchClient = cloudwatch_client or boto3.client(
            "cloudwatch", region_name=settings.region
        )

    def get_depth(self, queue_url: str) -> int:
        """Returns `ApproximateNumberOfMessages` -- an eventually-consistent
        SQS-side approximation, not an exact count; good enough for a
        composite health snapshot.
        """
        return self._get_attributes(queue_url)

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _get_attributes(self, queue_url: str) -> int:
        try:
            response = self._sqs.get_queue_attributes(
                QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessages"]
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _THROTTLE_CODES:
                raise ThrottlingError(str(exc)) from exc
            raise NonRetryableError(
                f"failed to read queue attributes for {queue_url}: {exc}"
            ) from exc
        return int(response.get("Attributes", {}).get("ApproximateNumberOfMessages", 0))

    def get_age_of_oldest_message(self, queue_url: str) -> int:
        """`ApproximateAgeOfOldestMessage` in seconds -- agents phase-17 §6
        Step 3: the watchdog scanner alarms `SessionKillQueue.fifo` when
        this exceeds 5 minutes. This is a CloudWatch metric in the `AWS/SQS`
        namespace, not an SQS `GetQueueAttributes` attribute -- SQS's own
        AttributeNames enum has no such member (that would raise
        `InvalidAttributeName` against a real queue); read via
        `cloudwatch:GetMetricStatistics` instead, over the last 5 minutes
        with `Maximum` (the metric is emitted at a 1-minute period, so a
        single most-recent-period read can miss the sample; Maximum over a
        short window is the standard way to read a still-fresh gauge).
        """
        return self._get_age_metric(queue_url)

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _get_age_metric(self, queue_url: str) -> int:
        now = datetime.now(UTC)
        try:
            response = self._cloudwatch.get_metric_statistics(
                Namespace="AWS/SQS",
                MetricName="ApproximateAgeOfOldestMessage",
                Dimensions=[{"Name": "QueueName", "Value": _queue_name(queue_url)}],
                StartTime=now - timedelta(minutes=5),
                # A datapoint stamped at ~now can land on or after a naive
                # `EndTime=now` and get excluded by boundary rounding --
                # pad the window into the future so the freshest sample is
                # never dropped by clock skew between the emit and the read.
                EndTime=now + timedelta(minutes=1),
                Period=60,
                Statistics=["Maximum"],
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _THROTTLE_CODES:
                raise ThrottlingError(str(exc)) from exc
            raise NonRetryableError(
                f"failed to read ApproximateAgeOfOldestMessage for {queue_url}: {exc}"
            ) from exc
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return 0
        return int(max(dp["Maximum"] for dp in datapoints))
