"""Never-revoke denylist (phase-06 §5 SAFETY: "Never revoke Sentinel's own
operator roles (denylist read from SSM parameter
`/sentinel/never-revoke-role-patterns`)"). Patterns use the same IAM
Resource-ARN glob grammar F1's `tools/f1/wildcard.py` resolves against --
`fnmatch.fnmatchcase`, not regex.
"""

from __future__ import annotations

from fnmatch import fnmatchcase

from iam_sentinel_adapters.ssm.client import SsmClient

from iam_sentinel_agents.settings import settings


def load_never_revoke_patterns(ssm_client: SsmClient | None = None) -> list[str]:
    client = ssm_client or SsmClient()
    return client.get_string_list(settings.never_revoke_ssm_param, default=[])


def is_denylisted(role_arn: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(role_arn, pattern) for pattern in patterns)
