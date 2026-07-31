"""STS AssumeRole into SentinelCrossAccountRole, cached and retried.

Every specialist tool that reads a member account's IAM/Organizations/Access
Analyzer/CloudTrail/Identity Center state goes through `assume()`. Credentials
are cached in the Lambda execution environment for their lifetime minus a
5-minute safety margin — a warm container reuses them across invocations
without a fresh AssumeRole call.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from iam_sentinel_agents.contracts.common import ACCOUNT_ID_PATTERN, FeatureID
from iam_sentinel_agents.errors import CrossAccountAssumeError
from iam_sentinel_agents.settings import settings

if TYPE_CHECKING:
    # boto3.client(...) is a factory FUNCTION, not a type — the real static
    # type of its return value comes from the boto3-stubs-generated stub
    # package instead.
    from mypy_boto3_sts.client import STSClient

_SAFETY_MARGIN = timedelta(minutes=5)
_RETRYABLE_ERROR_CODES = frozenset({"ThrottlingException", "ExpiredTokenException"})
_RETRY_DELAYS_SECONDS = (0.2, 0.5, 2.0)
_ACCOUNT_ID_RE = re.compile(ACCOUNT_ID_PATTERN)


@dataclass(frozen=True, slots=True)
class _CachedCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime

    def is_fresh(self, *, now: datetime) -> bool:
        return now < self.expiration - _SAFETY_MARGIN


class _CredentialCache:
    """Process-wide cache keyed by (account_id, role_name).

    A Lambda execution environment is single-threaded per invocation but
    can be reused across invocations; a lock guards concurrent cold-start
    races (e.g. provisioned concurrency warm-up) without adding meaningful
    latency to the common single-threaded path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], _CachedCredentials] = {}

    def get(self, account_id: str, role_name: str) -> _CachedCredentials | None:
        with self._lock:
            cached = self._entries.get((account_id, role_name))
        if cached is None:
            return None
        if not cached.is_fresh(now=datetime.now(UTC)):
            return None
        return cached

    def put(self, account_id: str, role_name: str, credentials: _CachedCredentials) -> None:
        with self._lock:
            self._entries[(account_id, role_name)] = credentials

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_CACHE = _CredentialCache()


def _regional_sts_client() -> STSClient:
    region = settings.region
    return boto3.client(
        "sts",
        region_name=region,
        endpoint_url=f"https://sts.{region}.amazonaws.com",
        # mode="standard" counts the initial attempt toward max_attempts, so
        # max_attempts=1 means botocore performs zero built-in retries — we
        # own retry timing explicitly in the loop below.
        config=Config(retries={"max_attempts": 1, "mode": "standard"}),
    )


def _assume_role_once(
    *, account_id: str, role_name: str, role_session_name: str, feature_id: FeatureID
) -> _CachedCredentials:
    sts = _regional_sts_client()
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=role_session_name,
        DurationSeconds=3600,
        # aws-infra ADR 0014 gates F2/F3/F5's mutating cross-account actions
        # on `aws:PrincipalTag/Feature` (crossaccount_stack.py); without a
        # session tag here that condition key never exists at runtime, so
        # every one of those Conditions would silently deny forever. Real
        # bug found while building F1 (agents phase-02) -- fixed here rather
        # than left for whichever specialist first tripped over it.
        Tags=[{"Key": "Feature", "Value": feature_id}],
        TransitiveTagKeys=["Feature"],
    )
    creds = response["Credentials"]
    return _CachedCredentials(
        access_key_id=creds["AccessKeyId"],
        secret_access_key=creds["SecretAccessKey"],
        session_token=creds["SessionToken"],
        expiration=creds["Expiration"],
    )


def assume(
    account_id: str,
    *,
    feature_id: FeatureID,
    correlation_id: str,
    role_name: str | None = None,
) -> boto3.Session:
    """Assume SentinelCrossAccountRole in `account_id` and return a session.

    Cached: a fresh call to STS only happens on a cold cache or when the
    cached credentials are within 5 minutes of expiring.

    Raises CrossAccountAssumeError after exhausting retries on
    ThrottlingException/ExpiredTokenException, or immediately on any other
    ClientError (notably AccessDenied — never retried).
    """
    if not _ACCOUNT_ID_RE.match(account_id):
        raise ValueError(f"account_id must be a 12-digit AWS account id, got {account_id!r}")

    resolved_role_name = role_name or settings.cross_account_role_name
    cached = _CACHE.get(account_id, resolved_role_name)
    if cached is not None:
        return _session_from_credentials(cached)

    role_session_name = f"sentinel-{feature_id.lower()}-{correlation_id[:8]}"

    last_error: ClientError | None = None
    for delay in (0.0, *_RETRY_DELAYS_SECONDS):
        if delay:
            time.sleep(delay)
        try:
            credentials = _assume_role_once(
                account_id=account_id,
                role_name=resolved_role_name,
                role_session_name=role_session_name,
                feature_id=feature_id,
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            last_error = exc
            if error_code not in _RETRYABLE_ERROR_CODES:
                raise CrossAccountAssumeError(account_id, resolved_role_name, cause=exc) from exc
            continue
        else:
            _CACHE.put(account_id, resolved_role_name, credentials)
            return _session_from_credentials(credentials)

    if last_error is None:  # pragma: no cover — defensive; loop always sets it on failure
        raise AssertionError("retry loop exited without a recorded error")
    raise CrossAccountAssumeError(account_id, resolved_role_name, cause=last_error)


def _session_from_credentials(credentials: _CachedCredentials) -> boto3.Session:
    return boto3.Session(
        aws_access_key_id=credentials.access_key_id,
        aws_secret_access_key=credentials.secret_access_key,
        aws_session_token=credentials.session_token,
        region_name=settings.region,
    )


def clear_cache_for_tests() -> None:
    """Test-only helper — production code never calls this."""
    _CACHE.clear()
