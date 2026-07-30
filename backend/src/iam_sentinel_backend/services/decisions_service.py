"""`GET /decisions`, `GET /decisions/{id}` (backend phase-01 §6)."""

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
from iam_sentinel_backend.schemas.decision import DecisionOut, DecisionsPage
from iam_sentinel_backend.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.decisions import DecisionsClient

    from iam_sentinel_backend.auth.principal import Principal


def _is_privileged(principal: Principal) -> bool:
    return principal.auth_kind == "sigv4" or principal.is_in_group(settings.cognito_group_auditors)


class DecisionsService:
    def __init__(self, decisions_client: DecisionsClient) -> None:
        self._decisions = decisions_client

    def list_decisions(
        self,
        *,
        principal: Principal,
        since_iso: str | None = None,
        principal_filter: str | None = None,
        limit: int = 25,
        next_token: str | None = None,
    ) -> DecisionsPage:
        target_principal = self._resolve_target_principal(principal, principal_filter)
        try:
            exclusive_start_key = decode_next_token(next_token)
        except InvalidNextTokenError as exc:
            raise SentinelHTTPException(
                code="INVALID_NEXT_TOKEN", message=str(exc), http_status=status.HTTP_400_BAD_REQUEST
            ) from exc

        items, last_key = self._decisions.list_page(
            target_principal,
            since_iso=since_iso,
            limit=clamp_limit(limit),
            exclusive_start_key=exclusive_start_key,
        )
        return DecisionsPage(
            items=[DecisionOut.model_validate(item) for item in items],
            next_token=encode_next_token(last_key),
        )

    def get_decision(self, *, principal: Principal, decision_id: str) -> DecisionOut:
        lookup_principal = None if _is_privileged(principal) else principal.arn
        item = self._decisions.get_by_id(decision_id, principal=lookup_principal)
        if item is None:
            raise SentinelHTTPException(
                code="DECISION_NOT_FOUND",
                message=f"no decision {decision_id!r}",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        if not _is_privileged(principal) and item.get("principal") != principal.arn:
            raise SentinelHTTPException(
                code="ACCESS_DENIED",
                message="cannot read another principal's decision",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        return DecisionOut.model_validate(item)

    def _resolve_target_principal(self, principal: Principal, requested: str | None) -> str:
        if _is_privileged(principal):
            return requested or principal.arn
        if requested is not None and requested != principal.arn:
            raise SentinelHTTPException(
                code="ACCESS_DENIED",
                message="cannot list another principal's decisions",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        return principal.arn
