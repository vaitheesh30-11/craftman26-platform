"""Thin STS wrapper (backend phase-00 §3: IAM SigV4 auth verification).

`backend/`'s SigV4 auth path needs `sts:GetCallerIdentity` to resolve the
caller's IAM ARN -- the boto3-only-through-adapters rule (README §1) means
that call cannot live inline in `backend/`. Added on-demand for this
consumer, same precedent as ADR 0006 ("add each [table client] on-demand
when the specialist or backend phase that needs it lands").
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import boto3
import requests
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import AccessDeniedError, NetworkError, ThrottlingError
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_sts import STSClient as _BotoStsClient

_STS_TIMEOUT_SECONDS = 5.0


class StsClient:
    """Wraps `sts:GetCallerIdentity` only -- the single STS action this
    module's auth path needs. No `AssumeRole`/`GetSessionToken` here; those
    live in `agents.tools.common.cross_account` for cross-account hops.
    """

    def __init__(self, *, session: requests.Session | None = None, client: _BotoStsClient | None = None) -> None:
        self._session = session or requests.Session()
        self._client: _BotoStsClient = client or boto3.client("sts", region_name=settings.region)

    def verify_signed_request(self, *, headers: dict[str, str], region: str | None = None) -> dict[str, str]:
        """Relay a caller-presigned `GetCallerIdentity` request to STS.

        The caller signs `GET https://sts.<region>.amazonaws.com/?Action=
        GetCallerIdentity&Version=2011-06-15` themselves -- their secret key
        never reaches Sentinel -- and hands over the resulting
        `Authorization`/`X-Amz-Date`/`X-Amz-Security-Token` headers. Relaying
        those exact headers to STS and trusting only STS's own signature
        check is the same verification pattern HashiCorp Vault's AWS auth
        method and `aws-iam-authenticator` use.
        """
        target_region = region or settings.region
        url = f"https://sts.{target_region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15"
        try:
            response = self._session.get(
                url,
                headers={**headers, "Accept": "application/json"},
                timeout=_STS_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise NetworkError(str(exc)) from exc

        if response.status_code == HTTPStatus.FORBIDDEN:
            raise AccessDeniedError(response.text[:500])
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise ThrottlingError(response.text[:500])
        if response.status_code != HTTPStatus.OK:
            raise NetworkError(f"STS GetCallerIdentity returned {response.status_code}: {response.text[:500]}")

        body = response.json()["GetCallerIdentityResponse"]["GetCallerIdentityResult"]
        return {"arn": str(body["Arn"]), "account": str(body["Account"]), "user_id": str(body["UserId"])}

    def whoami(self) -> dict[str, str]:
        """Resolve Sentinel's own runtime identity (Lambda execution role)."""
        try:
            response = self._client.get_caller_identity()
        except ClientError as exc:
            raise NetworkError(str(exc)) from exc
        return {"arn": str(response["Arn"]), "account": str(response["Account"]), "user_id": str(response["UserId"])}
