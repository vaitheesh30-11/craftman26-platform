"""`SentinelReports` bucket reader (backend phase-01 §7). Writers are each
specialist's own report Lambda (`agents/docs/phase-16-cost-guardrails.txt`
et al.) -- this client is read-only, matching backend's "never mutate a
bucket it doesn't own" convention.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import NonRetryableError, ThrottlingError, ValidationError
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_COST_PREFIX = "cost/"


class ReportsClient:
    def __init__(self, *, bucket: str | None = None, s3_client: S3Client | None = None) -> None:
        self._bucket = bucket or settings.reports_bucket
        self._s3: S3Client = s3_client or boto3.client("s3", region_name=settings.region)

    def get_latest_cost_report(self) -> tuple[str, dict[str, Any]] | None:
        """`cost/{year}-W{week}.json` keys sort lexicographically in the
        same order as chronologically -- zero-padded ISO week numbers keep
        `2026-W05` < `2026-W12` as plain strings -- so the lexicographically
        last key under the prefix is always the most recent report. Returns
        `(key, body)` so callers can surface which report they got.
        """
        latest_key = self._latest_key()
        if latest_key is None:
            return None
        raw_body = self._get_object(latest_key)
        try:
            body: dict[str, Any] = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"cost report {latest_key!r} is not valid JSON") from exc
        return latest_key, body

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _latest_key(self) -> str | None:
        try:
            response = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=_COST_PREFIX)
        except ClientError as exc:
            raise NonRetryableError(f"failed to list {self._bucket}/{_COST_PREFIX}: {exc}") from exc
        contents = response.get("Contents", [])
        if not contents:
            return None
        return str(max(contents, key=lambda obj: str(obj["Key"]))["Key"])

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _get_object(self, key: str) -> str:
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
        except self._s3.exceptions.NoSuchKey as exc:
            raise ValidationError(f"cost report {key!r} vanished between list and get") from exc
        body: str = response["Body"].read().decode("utf-8")
        return body
