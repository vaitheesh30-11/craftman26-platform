"""`functions/router` -- agents phase-15 §6 Step 1: the Router Lambda
`backend.services.router_bridge_service.RouterBridgeService` invokes
(`RouterBridgeService`'s own docstring names this exact module as its
not-yet-built callee). Every backend `/analyze/*`, `/enrich/policy`,
`/resolve/*`, `/scan/*`, `/emergency/kill-session` route already decided
`mode="fast"` and a fixed `target` at the URL-path level (phase-15 §4's
Router Policy Matrix rows for those exact paths); this handler's job is to
run that target's deterministic mirror (`tools/common/fast_path.py`) and
shape the result to match `backend.schemas.router_bridge.FastPathResponse`
exactly (`verdict`/`reason`/`findings`/`remediation`), or -- for the one
`GET` route -- `ShadowViolationsPage` (`items`/`next_token`).

`AmbiguityError` (§6 Step 2's escalation contract) is caught here and
reported back as `verdict="ESCALATE"` rather than actually re-dispatching
to the slow (Bedrock Agent) path: no `BedrockAgentRuntimeClient` call is
wired into this Lambda yet, same "code-complete, deploy deferred" gap as
every other specialist's CDK wiring (this phase's own ADR; ADR 0011/0015/
0017 precedent). `SentinelFastPathEscalations` still increments on this
path, per §6 Step 4, so the metric answering "how often does F<n> escalate"
is real from day one even before the slow-path hop physically exists.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit

from iam_sentinel_agents.ids import new_ulid
from iam_sentinel_agents.settings import settings

# Imported by name only to populate `_POST_DISPATCH_NAMES`/`globals()` below
# (so tests can `patch.object(router_fn, "passrole_fast", ...)` and have
# `_dispatch_post`'s dynamic lookup pick the patch up) -- never referenced
# by identifier in this module's own code, hence the blanket `noqa`.
from iam_sentinel_agents.tools.common.fast_path import (  # noqa: F401
    AmbiguityError,
    data_event_fast,
    emergency_kill_fast,
    org_context_fast,
    passrole_fast,
    scp_collision_fast,
    scp_impact_fast,
    shadow_guard_fast,
    slr_scan_fast,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_sso_admin.client import SSOAdminClient

    from iam_sentinel_agents.contracts.common import FeatureID

_SERVICE_NAME = "iam-sentinel-router"
_logger = Logger(service=_SERVICE_NAME, level=settings.log_level)
_tracer = Tracer(service=_SERVICE_NAME)
_metrics = Metrics(namespace=settings.metric_namespace, service=_SERVICE_NAME)

_ESCALATE_VERDICT = "ESCALATE"
_SLOW_PATH_NOT_WIRED_REASON = (
    "fast path is ambiguous and would normally escalate to the slow (Bedrock Agent) "
    "reasoning path, but no live InvokeAgent wiring exists yet for this Lambda "
    "(agents phase-15 ADR: code-complete, deploy deferred)"
)


class UnknownFastPathTargetError(ValueError):
    def __init__(self, target: str) -> None:
        super().__init__(f"no fast-path mirror registered for target {target!r}")


def _dispatch_f5(payload: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
    sso_client: SSOAdminClient = boto3.client("sso-admin", region_name=settings.region)
    return emergency_kill_fast(payload, correlation_id=correlation_id, sso_client=sso_client)


# Looked up by *name* (`globals()`), not by direct function reference, so
# tests can `patch.object(router_fn, "passrole_fast", ...)` and have this
# table's dispatch pick up the patch -- a dict of bound references captured
# at import time would not.
_POST_DISPATCH_NAMES: dict[str, str] = {
    "F1": "passrole_fast",
    "F2": "org_context_fast",
    "F3": "data_event_fast",
    "F4": "scp_impact_fast",
    "F5": "_dispatch_f5",
    "F7": "scp_collision_fast",
    "F8": "slr_scan_fast",
}


def _dispatch_post(target: FeatureID, payload: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
    name = _POST_DISPATCH_NAMES.get(target)
    if name is None:
        raise UnknownFastPathTargetError(target)
    mirror: Callable[..., dict[str, Any]] = globals()[name]
    return mirror(payload, correlation_id=correlation_id)


def _dispatch_read(target: FeatureID, query: dict[str, Any]) -> dict[str, Any]:
    if target == "F6":
        return shadow_guard_fast(query)
    raise UnknownFastPathTargetError(target)


def _emit_decision_metric(*, feature_id: str, outcome: str) -> None:
    _metrics.add_dimension(name="mode", value="fast")
    _metrics.add_dimension(name="feature_id", value=feature_id)
    _metrics.add_metric(name="SentinelRouterDecisions", unit=MetricUnit.Count, value=1)
    if outcome == "escalated":
        _metrics.add_metric(name="SentinelFastPathEscalations", unit=MetricUnit.Count, value=1)


@_metrics.log_metrics
@_tracer.capture_lambda_handler
def handler(event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """Matches `RouterBridgeService.dispatch`/`dispatch_read`'s exact
    request envelopes: `{"mode": "fast", "target": ..., "payload": ...,
    "principal": ..., "correlation_id": ...}` for a POST-backed route, or
    `{"mode": "fast", "target": ..., "query": {...}}` for the one GET.
    """
    start = time.monotonic()
    target: FeatureID = event["target"]
    correlation_id = str(event.get("correlation_id") or new_ulid())
    _logger.append_keys(correlation_id=correlation_id, feature_id=target)
    _tracer.put_annotation(key="correlation_id", value=correlation_id)
    _tracer.put_annotation(key="feature_id", value=target)

    try:
        if "query" in event:
            body = _dispatch_read(target, dict(event.get("query", {})))
            _emit_decision_metric(feature_id=target, outcome="success")
            return body

        payload = dict(event.get("payload", {}))
        body = _dispatch_post(target, payload, correlation_id=correlation_id)
        _emit_decision_metric(feature_id=target, outcome="success")
        return body
    except AmbiguityError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _logger.warning(
            "fast_path_ambiguous",
            target=target,
            reason=str(exc),
            duration_ms=duration_ms,
        )
        _emit_decision_metric(feature_id=target, outcome="escalated")
        return {
            "verdict": _ESCALATE_VERDICT,
            "reason": f"{exc}; {_SLOW_PATH_NOT_WIRED_REASON}",
            "findings": [],
            "remediation": None,
        }
    finally:
        _logger.remove_keys(("correlation_id", "feature_id"))
