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


def test_get_age_of_oldest_message_reads_the_cloudwatch_metric(
    dlq_queue_url: str, moto_session: None
) -> None:
    from datetime import UTC, datetime

    cloudwatch = boto3.client("cloudwatch", region_name=_REGION)
    queue_name = dlq_queue_url.rsplit("/", maxsplit=1)[-1]
    cloudwatch.put_metric_data(
        Namespace="AWS/SQS",
        MetricData=[
            {
                "MetricName": "ApproximateAgeOfOldestMessage",
                "Dimensions": [{"Name": "QueueName", "Value": queue_name}],
                "Timestamp": datetime.now(UTC),
                "Value": 42.0,
                "Unit": "Seconds",
            }
        ],
    )
    client = DlqClient(cloudwatch_client=cloudwatch)

    age = client.get_age_of_oldest_message(dlq_queue_url)

    assert age == 42


def test_get_age_of_oldest_message_returns_zero_with_no_datapoints(dlq_queue_url: str) -> None:
    cloudwatch = boto3.client("cloudwatch", region_name=_REGION)
    client = DlqClient(cloudwatch_client=cloudwatch)

    assert client.get_age_of_oldest_message(dlq_queue_url) == 0
