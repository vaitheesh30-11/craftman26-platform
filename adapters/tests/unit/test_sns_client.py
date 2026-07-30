from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_adapters.sns.client import SnsClient


class _ThrottledException(Exception):
    pass


def _fake_boto_client() -> MagicMock:
    client = MagicMock()
    client.exceptions.ThrottledException = _ThrottledException
    return client


def test_publish_critical_finding_returns_message_id() -> None:
    fake = _fake_boto_client()
    fake.publish.return_value = {"MessageId": "msg-1"}
    client = SnsClient(topic_arn="arn:aws:sns:us-east-1:111122223333:SentinelCriticalFindings", client=fake)

    message_id = client.publish_critical_finding(subject="CRITICAL finding", message="body")

    assert message_id == "msg-1"
    fake.publish.assert_called_once()


def test_publish_retries_on_throttling_then_succeeds() -> None:
    fake = _fake_boto_client()
    fake.publish.side_effect = [_ThrottledException("throttled"), {"MessageId": "msg-2"}]
    client = SnsClient(topic_arn="arn:aws:sns:us-east-1:111122223333:SentinelCriticalFindings", client=fake)

    message_id = client.publish_critical_finding(subject="CRITICAL finding", message="body")

    assert message_id == "msg-2"
    assert fake.publish.call_count == 2
