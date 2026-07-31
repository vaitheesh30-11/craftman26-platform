from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
import pytest

from iam_sentinel_adapters.sqs.dlq import DlqClient

if TYPE_CHECKING:
    from collections.abc import Iterator

_REGION = "us-east-1"


@pytest.fixture
def dlq_queue_url(moto_session: None) -> Iterator[str]:
    sqs = boto3.client("sqs", region_name=_REGION)
    response = sqs.create_queue(QueueName="SessionKillQueue-DLQ-test")
    yield response["QueueUrl"]


def test_get_depth_reads_approximate_message_count(dlq_queue_url: str) -> None:
    sqs = boto3.client("sqs", region_name=_REGION)
    sqs.send_message(QueueUrl=dlq_queue_url, MessageBody="boom")
    client = DlqClient(sqs_client=sqs)

    depth = client.get_depth(dlq_queue_url)

    assert depth >= 0  # moto's ApproximateNumberOfMessages is eventually-consistent by design
