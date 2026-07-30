from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_adapters.security_hub.client import SecurityHubClient


class _LimitExceededException(Exception):
    pass


def _fake_boto_client() -> MagicMock:
    client = MagicMock()
    client.exceptions.LimitExceededException = _LimitExceededException
    return client


def test_batches_at_100_findings_per_call() -> None:
    fake = _fake_boto_client()
    fake.batch_import_findings.return_value = {"SuccessCount": 100, "FailedCount": 0, "FailedFindings": []}
    client = SecurityHubClient(client=fake)

    findings = [{"Id": str(i)} for i in range(150)]
    result = client.import_findings(findings)

    assert fake.batch_import_findings.call_count == 2
    assert result.success_count == 200


def test_retries_on_limit_exceeded_then_succeeds() -> None:
    fake = _fake_boto_client()
    fake.batch_import_findings.side_effect = [
        _LimitExceededException("throttled"),
        {"SuccessCount": 1, "FailedCount": 0, "FailedFindings": []},
    ]
    client = SecurityHubClient(client=fake)

    result = client.import_findings([{"Id": "1"}])

    assert result.success_count == 1
    assert fake.batch_import_findings.call_count == 2


def test_accumulates_failed_findings_across_batches() -> None:
    fake = _fake_boto_client()
    fake.batch_import_findings.return_value = {
        "SuccessCount": 0,
        "FailedCount": 1,
        "FailedFindings": [{"Id": "bad", "ErrorMessage": "nope"}],
    }
    client = SecurityHubClient(client=fake)

    result = client.import_findings([{"Id": "bad"}])

    assert result.failed_count == 1
    assert result.failed_findings == [{"Id": "bad", "ErrorMessage": "nope"}]
