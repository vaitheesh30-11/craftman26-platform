"""Shared Lambda entrypoint helpers for every IAM Sentinel tool.

`sentinel_handler(feature_id=...)` is the ONE decorator every tool Lambda
uses. It owns: Logger/Tracer/Metrics setup, envelope parsing, correlation_id
propagation, exception-to-HTTP-status mapping, input/output hashing, and the
structured `tool_completed` log line that the eval harness and CloudWatch
dashboards both consume (see agents/docs/phase-12-observability-evals.txt
§4). Handlers decorated with it never see a raw Bedrock event — only a typed
`ParsedInvocation`.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any, cast, TYPE_CHECKING, TypeVar

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

from iam_sentinel_agents.contracts.verdict import ToolInvocation
from iam_sentinel_agents.errors import ContractError
from iam_sentinel_agents.settings import settings
from iam_sentinel_agents.tools.common.event_parser import (
    build_action_group_response,
    build_fallback_error_response,
    parse_action_group,
    ParsedInvocation,
)

if TYPE_CHECKING:
    # Referenced only inside deferred (PEP 563) annotations below — never
    # evaluated eagerly, so ruff (TCH) wants them import-time-free.
    from iam_sentinel_agents.contracts.common import FeatureID
    from iam_sentinel_agents.contracts.remediation import ZelkovaCheck

ToolFunc = TypeVar("ToolFunc", bound=Callable[[ParsedInvocation, LambdaContext], dict[str, Any]])
LambdaHandler = Callable[[dict[str, Any], LambdaContext], dict[str, Any]]

_LOG_CONTEXT_KEYS = ("correlation_id", "feature_id", "tool_name")
_cold_start_seen: set[str] = set()


def _canonical_hash(payload: dict[str, Any]) -> str:
    """RFC-8785-adjacent canonicalization: sorted keys, no whitespace, UTF-8.

    Good enough for hashing (deterministic, stable across dict-ordering) —
    the fully spec-compliant JCS implementation lives in adapters/evidence
    (agents phase-10... adapters phase-04) for signed evidence blobs.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_tool_invocation(
    *,
    tool_name: str,
    input_hash: str,
    output_hash: str,
    duration_ms: int,
    zelkova_check: ZelkovaCheck | None = None,
) -> ToolInvocation:
    """Construct a `ToolInvocation` from hashes computed by the runtime.

    Tool Lambdas return plain JSON bodies matching their OpenAPI response
    schema — never a `ToolInvocation` wrapper, which would confuse the
    Bedrock model reading the response. The hashes this decorator computes
    are instead emitted in the `tool_completed` structured log line; the
    Supervisor's post-turn Lambda (phase-01) reconstructs `ToolInvocation`
    entries for the final `DecisionRecord` by correlating that log line
    with the X-Ray trace via `correlation_id`. This helper exists so that
    reconstruction — and any test asserting it — shares one code path.
    """
    return ToolInvocation(
        tool_name=tool_name,
        input_hash=input_hash,
        output_hash=output_hash,
        duration_ms=duration_ms,
        zelkova_check=zelkova_check,
    )


def sentinel_handler(
    feature_id: FeatureID, *, tool_name: str | None = None
) -> Callable[[ToolFunc], LambdaHandler]:
    """Decorator turning a typed tool function into a Bedrock Lambda handler.

    The wrapped function must have the signature
    `(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]`
    and return a plain dict matching its action group's OpenAPI response
    schema. Everything else — parsing, logging, tracing, metrics, hashing,
    envelope construction — is handled here.
    """
    service_name = f"iam-sentinel-{feature_id.lower()}"
    logger = Logger(service=service_name, level=settings.log_level)
    tracer = Tracer(service=service_name)
    metrics = Metrics(namespace=settings.metric_namespace, service=service_name)

    def decorator(func: ToolFunc) -> LambdaHandler:
        resolved_tool_name = tool_name or func.__name__

        @tracer.capture_lambda_handler
        def wrapper(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
            is_cold_start = resolved_tool_name not in _cold_start_seen
            _cold_start_seen.add(resolved_tool_name)
            start = time.monotonic()

            try:
                invocation = parse_action_group(event)
            except ContractError as exc:
                logger.warning("rejected_envelope", tool_name=resolved_tool_name, error=str(exc))
                _emit_invocation_metric(
                    metrics, feature_id=feature_id, outcome="rejected", cold_start=is_cold_start
                )
                return build_fallback_error_response(event, http_status=400, message=str(exc))

            logger.append_keys(
                correlation_id=invocation.correlation_id,
                feature_id=feature_id,
                tool_name=resolved_tool_name,
            )
            tracer.put_annotation(key="correlation_id", value=invocation.correlation_id)
            tracer.put_annotation(key="feature_id", value=feature_id)

            try:
                input_hash = _canonical_hash(invocation.parameters)
                try:
                    body = func(invocation, context)
                except Exception as exc:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    logger.exception("tool_failed", tool_name=resolved_tool_name)
                    _emit_invocation_metric(
                        metrics,
                        feature_id=feature_id,
                        outcome="error",
                        cold_start=is_cold_start,
                    )
                    _log_tool_completed(
                        logger,
                        tool_name=resolved_tool_name,
                        input_hash=input_hash,
                        output_hash=_canonical_hash({"error": str(exc)}),
                        duration_ms=duration_ms,
                        cold_start=is_cold_start,
                        aws_request_id=context.aws_request_id,
                    )
                    return build_action_group_response(
                        invocation, http_status=500, body={"error": str(exc)}
                    )

                duration_ms = int((time.monotonic() - start) * 1000)
                output_hash = _canonical_hash(body)
                _emit_invocation_metric(
                    metrics,
                    feature_id=feature_id,
                    outcome="success",
                    cold_start=is_cold_start,
                )
                _log_tool_completed(
                    logger,
                    tool_name=resolved_tool_name,
                    input_hash=input_hash,
                    output_hash=output_hash,
                    duration_ms=duration_ms,
                    cold_start=is_cold_start,
                    aws_request_id=context.aws_request_id,
                )
                return build_action_group_response(invocation, http_status=200, body=body)
            finally:
                logger.remove_keys(_LOG_CONTEXT_KEYS)

        # cast, not `# type: ignore`: whether Powertools' TypeVar-based stubs
        # already preserve `wrapper`'s exact signature or widen it to Any
        # varies by version, and an unused `type: ignore` is itself a mypy
        # --strict error. cast() is correct either way.
        return cast("LambdaHandler", metrics.log_metrics(wrapper))

    return decorator


def _emit_invocation_metric(
    metrics: Metrics, *, feature_id: FeatureID, outcome: str, cold_start: bool
) -> None:
    metrics.add_dimension(name="feature_id", value=feature_id)
    metrics.add_dimension(name="outcome", value=outcome)
    metrics.add_metric(name="SentinelInvocation", unit=MetricUnit.Count, value=1)
    if cold_start:
        metrics.add_metric(name="ColdStart", unit=MetricUnit.Count, value=1)


def reset_cold_start_tracking_for_tests() -> None:
    """Test-only helper — production code never calls this."""
    _cold_start_seen.clear()


def _log_tool_completed(
    logger: Logger,
    *,
    tool_name: str,
    input_hash: str,
    output_hash: str,
    duration_ms: int,
    cold_start: bool,
    aws_request_id: str,
) -> None:
    logger.info(
        "tool_completed",
        tool_name=tool_name,
        input_hash=f"sha256:{input_hash}",
        output_hash=f"sha256:{output_hash}",
        duration_ms=duration_ms,
        zelkova=None,
        cold_start=cold_start,
        aws_request_id=aws_request_id,
    )
