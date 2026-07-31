"""`GET /reports/weekly/{report_kind}`, `GET /reports/{key:path}` read
models (backend phase-04 §2/§3). One shape covers both endpoints -- neither
distinguishes report kinds at the wire level, only at the S3-prefix
resolution step `ReportsClient` owns.
"""

from __future__ import annotations

from pydantic import Field

from iam_sentinel_backend.schemas.common import ResponseBase


class ReportOut(ResponseBase):
    """`retrieved_from_s3_key` per phase-04 §4 step 1 -- callers can always
    see exactly which report they got, even for the "latest of a kind"
    endpoint where the key itself isn't part of the request.
    """

    retrieved_from_s3_key: str
    body: dict[str, object] = Field(default_factory=dict)
