"""Security Hub ASFF import client (phase-04 §9-11).

Batches at Security Hub's 100-finding-per-call limit and retries on
`LimitExceededException` with the `AGGRESSIVE` retry policy (phase-00
`retry.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import boto3

from iam_sentinel_adapters.errors import ThrottlingError
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_securityhub import SecurityHubClient as _BotoSecurityHubClient

_BATCH_SIZE = 100


@dataclass(frozen=True)
class BatchImportResult:
    success_count: int = 0
    failed_count: int = 0
    failed_findings: list[dict[str, Any]] = field(default_factory=list)


class SecurityHubClient:
    def __init__(self, *, client: _BotoSecurityHubClient | None = None) -> None:
        self._client: _BotoSecurityHubClient = client or boto3.client(
            "securityhub", region_name=settings.region
        )

    def import_findings(self, findings: list[dict[str, Any]]) -> BatchImportResult:
        result = BatchImportResult()
        for start in range(0, len(findings), _BATCH_SIZE):
            batch = findings[start : start + _BATCH_SIZE]
            response = self._import_batch(batch)
            result = BatchImportResult(
                success_count=result.success_count + response["SuccessCount"],
                failed_count=result.failed_count + response["FailedCount"],
                failed_findings=[*result.failed_findings, *response.get("FailedFindings", [])],
            )
        return result

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _import_batch(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            return dict(self._client.batch_import_findings(Findings=batch))  # type: ignore[arg-type]
        except self._client.exceptions.LimitExceededException as exc:
            raise ThrottlingError(str(exc)) from exc
