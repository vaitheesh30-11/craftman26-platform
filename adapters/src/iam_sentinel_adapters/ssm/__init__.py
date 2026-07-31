"""Cached `ssm:GetParameter` reads (backend phase-03 §3 step 3)."""

from __future__ import annotations

from iam_sentinel_adapters.ssm.params import SsmParameterClient

__all__ = ["SsmParameterClient"]
