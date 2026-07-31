"""Thin SQS FIFO send wrapper (agents phase-06 §3 Step 2: fan-out from
`session_kill_dispatch` to `SessionKillQueue.fifo`, one message per
`(account_id, role_arn)` with `MessageGroupId=account_id` for per-account
ordering). No adapter wrapped SQS before this phase (only ddb/evidence/kb/
llm/security_hub/sns/zelkova existed) -- added on-demand for the first
caller that needs it, same precedent as ADR 0006's DDB scope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import ThrottlingError
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient as _BotoSqsClient


class SqsClient:
    def __init__(
        self, *, queue_url: str | None = None, client: _BotoSqsClient | None = None
    ) -> None:
        self._queue_url = queue_url or settings.session_kill_queue_url
        self._client: _BotoSqsClient = client or boto3.client("sqs", region_name=settings.region)

    def send_fifo_message(self, *, message_group_id: str, deduplication_id: str, body: str) -> str:
        response = self._send(
            message_group_id=message_group_id, deduplication_id=deduplication_id, body=body
        )
        return str(response["MessageId"])

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _send(self, *, message_group_id: str, deduplication_id: str, body: str) -> dict[str, Any]:
        try:
            return dict(
                self._client.send_message(
                    QueueUrl=self._queue_url,
                    MessageBody=body,
                    MessageGroupId=message_group_id,
                    MessageDeduplicationId=deduplication_id,
                )
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"ThrottlingException", "RequestThrottled"}:
                raise ThrottlingError(str(exc)) from exc
            raise
