"""SSM Parameter Store read wrappers."""

from __future__ import annotations

from iam_sentinel_adapters.ssm.client import SsmClient
from iam_sentinel_adapters.ssm.params import SsmParameterClient

__all__ = ["SsmClient", "SsmParameterClient"]
