"""Fast-path routes (backend phase-01 §3, §5): `/analyze/*`, `/enrich/
policy`, `/resolve/*`, `/scan/*`, `/emergency/kill-session`, `/monitor/
shadow-violations`. All but `/emergency/kill-session` are `Cognito+IAM`
auth (`get_principal` alone, same as every other router); `/emergency/*`
additionally requires the break-glass session tag (`require_breakglass`,
phase-00 §3) -- backend phase-01 §9's acceptance criterion "`/emergency/
kill-session` refuses without BreakGlass tag" is enforced by that
dependency raising 403 before this handler ever runs.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends

from iam_sentinel_backend.deps import (
    get_correlation_id,
    get_principal,
    get_router_bridge_service,
    require_breakglass,
)
from iam_sentinel_backend.envelope import ok
from iam_sentinel_backend.schemas.router_bridge import FastPathRequest

if TYPE_CHECKING:
    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.services.router_bridge_service import RouterBridgeService

router = APIRouter(tags=["router_bridge"])


def _dispatch(
    target: str,
    request: FastPathRequest,
    principal: Principal,
    correlation_id: str,
    router_bridge_service: RouterBridgeService,
) -> dict[str, Any]:
    result = router_bridge_service.dispatch(
        target=target,  # type: ignore[arg-type]
        payload=request.payload,
        principal=principal,
        correlation_id=correlation_id,
    )
    return ok(result)


@router.post("/analyze/passrole")
def analyze_passrole(
    request: FastPathRequest,
    principal: Principal = Depends(get_principal),
    correlation_id: str = Depends(get_correlation_id),
    router_bridge_service: RouterBridgeService = Depends(get_router_bridge_service),
) -> dict[str, Any]:
    return _dispatch("F1", request, principal, correlation_id, router_bridge_service)


@router.post("/analyze/org-context")
def analyze_org_context(
    request: FastPathRequest,
    principal: Principal = Depends(get_principal),
    correlation_id: str = Depends(get_correlation_id),
    router_bridge_service: RouterBridgeService = Depends(get_router_bridge_service),
) -> dict[str, Any]:
    return _dispatch("F2", request, principal, correlation_id, router_bridge_service)


@router.post("/enrich/policy")
def enrich_policy(
    request: FastPathRequest,
    principal: Principal = Depends(get_principal),
    correlation_id: str = Depends(get_correlation_id),
    router_bridge_service: RouterBridgeService = Depends(get_router_bridge_service),
) -> dict[str, Any]:
    return _dispatch("F3", request, principal, correlation_id, router_bridge_service)


@router.post("/analyze/scp-impact")
def analyze_scp_impact(
    request: FastPathRequest,
    principal: Principal = Depends(get_principal),
    correlation_id: str = Depends(get_correlation_id),
    router_bridge_service: RouterBridgeService = Depends(get_router_bridge_service),
) -> dict[str, Any]:
    return _dispatch("F4", request, principal, correlation_id, router_bridge_service)


@router.post("/emergency/kill-session")
def emergency_kill_session(
    request: FastPathRequest,
    principal: Principal = Depends(require_breakglass),
    correlation_id: str = Depends(get_correlation_id),
    router_bridge_service: RouterBridgeService = Depends(get_router_bridge_service),
) -> dict[str, Any]:
    return _dispatch("F5", request, principal, correlation_id, router_bridge_service)


@router.get("/monitor/shadow-violations")
def monitor_shadow_violations(
    _principal: Principal = Depends(get_principal),
    router_bridge_service: RouterBridgeService = Depends(get_router_bridge_service),
) -> dict[str, Any]:
    result = router_bridge_service.dispatch_read(target="F6", query={})
    return ok(result)


@router.post("/resolve/scp-collisions")
def resolve_scp_collisions(
    request: FastPathRequest,
    principal: Principal = Depends(get_principal),
    correlation_id: str = Depends(get_correlation_id),
    router_bridge_service: RouterBridgeService = Depends(get_router_bridge_service),
) -> dict[str, Any]:
    return _dispatch("F7", request, principal, correlation_id, router_bridge_service)


@router.post("/scan/slr-breakage")
def scan_slr_breakage(
    request: FastPathRequest,
    principal: Principal = Depends(get_principal),
    correlation_id: str = Depends(get_correlation_id),
    router_bridge_service: RouterBridgeService = Depends(get_router_bridge_service),
) -> dict[str, Any]:
    return _dispatch("F8", request, principal, correlation_id, router_bridge_service)
