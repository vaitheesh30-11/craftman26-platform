"""Thin SSM Parameter Store read wrapper.

First (and so far only) caller is F5's never-revoke denylist (agents
phase-06 §5 SAFETY: "denylist read from SSM parameter
`/sentinel/never-revoke-role-patterns`") -- a `StringList` parameter, comma
-separated, read fresh on every dispatch rather than cached, since a
denylist update must take effect on the very next emergency revocation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3

from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_ssm import SSMClient as _BotoSsmClient


class SsmClient:
    def __init__(self, *, client: _BotoSsmClient | None = None) -> None:
        self._client: _BotoSsmClient = client or boto3.client("ssm", region_name=settings.region)

    def get_string_list(self, name: str, *, default: list[str] | None = None) -> list[str]:
        try:
            response = self._client.get_parameter(Name=name)
        except self._client.exceptions.ParameterNotFound:
            return list(default) if default else []
        value = response["Parameter"].get("Value", "")
        return [item.strip() for item in value.split(",") if item.strip()]
