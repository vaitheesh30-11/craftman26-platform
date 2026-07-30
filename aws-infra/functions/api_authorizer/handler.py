"""`SentinelApi` REQUEST-type Lambda authorizer (phase-07 §6).

Per ADR 0017, one Lambda authorizer covers both authorizer bullets in the
spec -- "Cognito JWT authorizer" and "Lambda authorizer for machine callers
(IAM-signed)" -- because a single API Gateway method can only carry one
`authorizationType`; a hand-rolled decision tree is the only way both a
human (Cognito) and a machine (SigV4) caller can reach the same route.

Two verification paths, mirroring `backend`'s own two paths
(`iam_sentinel_backend.auth.cognito`/`sigv4`) but re-implemented here with
zero third-party dependencies (only `boto3`, already in the shared layer;
no PyJWT/`requests` -- see ADR 0017's packaging-gap note):

1. **Cognito access token.** `Authorization: Bearer <access_token>` ->
   `cognito-idp:GetUser`. Delegating verification to Cognito itself avoids
   needing a local JWKS/RS256 implementation; `GetUser` raises
   `NotAuthorizedException` for any expired/invalid/revoked token, which is
   exactly the check we need.
2. **Relayed SigV4 `GetCallerIdentity`.** Any other `Authorization` value
   is treated as a caller-presigned STS request; its headers are relayed
   verbatim to `https://sts.<region>.amazonaws.com/` via `urllib` (stdlib,
   no `requests`). Only STS's own signature check is trusted, per the same
   pattern `iam_sentinel_backend.auth.sigv4.SigV4Verifier` documents.

`/emergency/*` does NOT get extra treatment here: per ADR 0017, the
break-glass two-signer tag (`aws:PrincipalTag/BreakGlass`) cannot be
recovered from a resolved caller ARN by any AWS read API (session tags are
transient, not queryable after `AssumeRole`) -- so that path is gated by a
native `AWS_IAM` resource-policy condition at the API Gateway layer
instead (see `api_stack.py::_build_emergency_resource_policy`), evaluated
by IAM before this authorizer would ever run. This authorizer is not
attached to `/emergency/*` at all.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

import boto3
from botocore.exceptions import ClientError

_cognito = boto3.client("cognito-idp")

_STS_RELAY_TIMEOUT_SECONDS = 5.0


class AuthorizerDeniedError(Exception):
    """Raised for any verification failure; `handler` maps this to Deny."""


def _verify_cognito_access_token(token: str) -> dict[str, Any]:
    try:
        response = _cognito.get_user(AccessToken=token)
    except ClientError as exc:
        raise AuthorizerDeniedError(f"Cognito GetUser rejected the access token: {exc}") from exc

    attributes = {a["Name"]: a["Value"] for a in response.get("UserAttributes", [])}
    sub = attributes.get("sub")
    if not sub:
        raise AuthorizerDeniedError("Cognito GetUser response missing 'sub' attribute")
    return {"auth_kind": "cognito", "principal": sub, "username": response.get("Username", sub)}


def _relay_get_caller_identity(headers: dict[str, str]) -> dict[str, Any]:
    """Relays the caller's own presigned `GetCallerIdentity` request to STS.
    The caller is trusted only insofar as STS itself validates their SigV4
    signature -- this function never inspects or trusts the signature
    itself, matching `StsClient.verify_signed_request`'s pattern.
    """
    host = headers.get("Host") or headers.get("host")
    if not host:
        raise AuthorizerDeniedError(
            "SigV4 relay requires a Host header identifying the STS endpoint"
        )
    scheme_host = host if host.startswith("http") else f"https://{host}"
    parsed = urlsplit(scheme_host)
    if (
        not parsed.hostname
        or "sts." not in parsed.hostname
        and parsed.hostname != "sts.amazonaws.com"
    ):
        raise AuthorizerDeniedError(
            f"refusing to relay a presigned request to non-STS host {host!r}"
        )

    request = urllib.request.Request(
        url=f"https://{parsed.hostname}/",
        data=b"Action=GetCallerIdentity&Version=2011-06-15",
        headers={k: v for k, v in headers.items() if k.lower() != "host"},
        method="POST",
    )
    try:
        # scheme is always "https" -- built two lines above, never taken from
        # caller input directly (the Host header only supplies the hostname).
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=_STS_RELAY_TIMEOUT_SECONDS
        ) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise AuthorizerDeniedError(f"STS relay failed: {exc}") from exc

    if "<Arn>" not in body:
        raise AuthorizerDeniedError("STS GetCallerIdentity response missing <Arn>")
    arn = body.split("<Arn>", 1)[1].split("</Arn>", 1)[0]
    return {"auth_kind": "sigv4", "principal": arn}


def _resolve_identity(event: dict[str, Any]) -> dict[str, Any]:
    headers = event.get("headers") or {}
    authorization = headers.get("Authorization") or headers.get("authorization")
    if not authorization:
        raise AuthorizerDeniedError("missing Authorization header")

    if authorization.startswith("AWS4-HMAC-SHA256"):
        return _relay_get_caller_identity(headers)

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise AuthorizerDeniedError("Authorization header carried no bearer token")
    return _verify_cognito_access_token(token)


def _policy(
    principal_id: str, effect: str, method_arn: str, context: dict[str, str]
) -> dict[str, Any]:
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": effect, "Resource": method_arn}
            ],
        },
        "context": context,
    }


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    method_arn = event["methodArn"]
    try:
        identity = _resolve_identity(event)
    except AuthorizerDeniedError as exc:
        # API Gateway REQUEST authorizers must raise "Unauthorized" (via a
        # thrown error) to produce a 401; returning an explicit Deny policy
        # instead yields a 403, which would mask the distinction backend's
        # own error envelope (`errors.py`) already draws between the two.
        raise Exception("Unauthorized") from exc

    context = {"authKind": identity["auth_kind"], "principal": identity["principal"]}
    return _policy(identity["principal"], "Allow", method_arn, context)
