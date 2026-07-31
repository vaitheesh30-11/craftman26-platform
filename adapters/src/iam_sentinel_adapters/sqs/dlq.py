"""`sqs:GetQueueAttributes` wrapper for DLQ depth reads (backend phase-04
§2/§4 step 2 -- `GET /operations/health`). Which queue URLs count as "every
DLQ" is settings-driven, not discovered (see `AdapterSettings.dlq_queue_urls`
and ADR 0023) -- this client only knows how to read the depth of a queue URL
it is given.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import NonRetryableError, ThrottlingError
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient

_THROTTLE_CODES = {"ThrottlingException", "RequestThrottled"}


class DlqClient:
    def __init__(self, *, sqs_client: SQSClient | None = None) -> None:
        self._sqs: SQSClient = sqs_client or boto3.client("sqs", region_name=settings.region)

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
        this exceeds 5 minutes. Same eventually-consistent SQS-side
        approximation caveat as `get_depth`.
        """
        return self._get_age_attribute(queue_url)

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _get_age_attribute(self, queue_url: str) -> int:
        try:
            response = self._sqs.get_queue_attributes(
                QueueUrl=queue_url, AttributeNames=["ApproximateAgeOfOldestMessage"]
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _THROTTLE_CODES:
                raise ThrottlingError(str(exc)) from exc
            raise NonRetryableError(
                f"failed to read queue attributes for {queue_url}: {exc}"
            ) from exc
        return int(response.get("Attributes", {}).get("ApproximateAgeOfOldestMessage", 0))
