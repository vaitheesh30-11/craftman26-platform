"""S3 helpers beyond the evidence bucket (`iam_sentinel_adapters.evidence`).
Currently just `SentinelReports` read access for `GET /operations/cost/weekly`
(backend phase-01 §7).
"""

from __future__ import annotations

from iam_sentinel_adapters.s3.reports import ReportsClient

__all__ = ["ReportsClient"]
