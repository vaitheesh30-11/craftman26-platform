"""SNS publish for critical-finding alarms (phase-01 §3.2 step 6)."""

from __future__ import annotations

from iam_sentinel_adapters.sns.client import SnsClient

__all__ = ["SnsClient"]
