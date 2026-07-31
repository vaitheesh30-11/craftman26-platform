from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import ThrottlingError
from iam_sentinel_adapters.sqs.client import SqsClient


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "SendMessage")


def test_send_fifo_message_returns_message_id() -> None:
    mock_sqs = MagicMock()
    mock_sqs.send_message.return_value = {"MessageId": "m1"}
    client = SqsClient(queue_url="https://sqs.example/q.fifo", client=mock_sqs)

    message_id = client.send_fifo_message(
        message_group_id="111122223333", deduplication_id="dedupe-1", body="{}"
    )

    assert message_id == "m1"
    mock_sqs.send_message.assert_called_once_with(
        QueueUrl="https://sqs.example/q.fifo",
        MessageBody="{}",
        MessageGroupId="111122223333",
        MessageDeduplicationId="dedupe-1",
    )


def test_send_fifo_message_translates_throttling_error() -> None:
    mock_sqs = MagicMock()
    mock_sqs.send_message.side_effect = _client_error("ThrottlingException")
    client = SqsClient(queue_url="https://sqs.example/q.fifo", client=mock_sqs)

    with pytest.raises(ThrottlingError):
        client.send_fifo_message(message_group_id="g", deduplication_id="d", body="{}")


def test_send_fifo_message_reraises_non_throttling_client_error() -> None:
    mock_sqs = MagicMock()
    mock_sqs.send_message.side_effect = _client_error("AccessDenied")
    client = SqsClient(queue_url="https://sqs.example/q.fifo", client=mock_sqs)

    with pytest.raises(ClientError):
        client.send_fifo_message(message_group_id="g", deduplication_id="d", body="{}")
