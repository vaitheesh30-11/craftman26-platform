"""`GET /findings`, `GET /findings/{id}` (backend phase-01 §6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.pagination import (
    clamp_limit,
    decode_next_token,
    encode_next_token,
    InvalidNextTokenError,
)
from iam_sentinel_backend.schemas.finding import FindingOut, FindingsPage
from iam_sentinel_backend.settings import settings

if TYPE_CHECKING:
    from datetime import datetime

    from iam_sentinel_adapters.ddb.findings import FindingsClient

    from iam_sentinel_backend.auth.principal import Principal


def _is_privileged(principal: Principal) -> bool:
    # SigV4 callers are machine/CI callers (tagged `Purpose=
    # SentinelMachineCaller` per aws-infra phase-07 §6), not the human
    # end-users the per-principal scoping rule protects -- treated the same
    # as Auditors for read scope.
    return principal.auth_kind == "sigv4" or principal.is_in_group(settings.cognito_group_auditors)


class FindingsService:
    def __init__(self, findings_client: FindingsClient) -> None:
        self._findings = findings_client

    def list_findings(
        self,
        *,
        principal: Principal,
        severity: str | None = None,
        feature_id: str | None = None,
        account_id: str | None = None,
        principal_arn: str | None = None,
        since: datetime | None = None,
        limit: int = 25,
        next_token: str | None = None,
    ) -> FindingsPage:
        scoped_principal_arn = self._scope_read(principal, principal_arn)
        try:
            exclusive_start_key = decode_next_token(next_token)
        except InvalidNextTokenError as exc:
            raise SentinelHTTPException(
                code="INVALID_NEXT_TOKEN", message=str(exc), http_status=status.HTTP_400_BAD_REQUEST
            ) from exc

        items, last_key = self._findings.list_page(
            account_id=account_id,
            feature_id=feature_id,
            severity=severity,
            principal_arn=scoped_principal_arn,
            since=since,
            limit=clamp_limit(limit),
            exclusive_start_key=exclusive_start_key,
        )
        return FindingsPage(
            items=[FindingOut.model_validate(item) for item in items],
            next_token=encode_next_token(last_key),
        )

    def get_finding(
        self,
        *,
        principal: Principal,
        finding_id: str,
        account_id: str | None = None,
        feature_id: str | None = None,
    ) -> FindingOut:
        item = (
            self._findings.get(account_id, feature_id, finding_id)
            if account_id and feature_id
            else self._findings.get_by_id(finding_id)
        )
        if item is None:
            raise SentinelHTTPException(
                code="FINDING_NOT_FOUND",
                message=f"no finding {finding_id!r}",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        if not _is_privileged(principal) and item.get("principal_arn") != principal.arn:
            # Deny-by-default for cross-principal reads (backend phase-01 §9
            # acceptance criterion) -- including findings with no
            # `principal_arn` at all (account/resource-scoped findings),
            # which a non-Auditor has no standing claim to either.
            raise SentinelHTTPException(
                code="ACCESS_DENIED",
                message="cannot read another principal's finding",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        return FindingOut.model_validate(item)

    def _scope_read(self, principal: Principal, requested_principal_arn: str | None) -> str | None:
        if _is_privileged(principal):
            return requested_principal_arn
        if requested_principal_arn is not None and requested_principal_arn != principal.arn:
            raise SentinelHTTPException(
                code="ACCESS_DENIED",
                message="cannot filter findings by another principal_arn",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        return principal.arn
