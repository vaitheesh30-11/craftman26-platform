"""`MemoryActions` -- the one Bedrock action group shared by Prime and
every specialist (phase-14 §2/§4). Not built on `tools.common.runtime.
sentinel_handler`: that decorator is parameterized by a single `FeatureID`
("F1".."F8") for its metrics dimension and log context, but this action
group is deliberately feature-agnostic -- every specialist attaches the
same `MemoryActions` group. This module hand-rolls the same envelope-
parsing / structured-logging / error-mapping shape `sentinel_handler`
gives every other tool, scoped to `feature_id="MEMORY"` as its own
dimension instead.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from iam_sentinel_adapters.memory.client import MemoryClient
from iam_sentinel_adapters.settings import settings as adapter_settings

from iam_sentinel_agents.contracts.memory import EpisodicMemory, SemanticEntity
from iam_sentinel_agents.errors import (
    ContractError,
    MemoryIsolationError,
    MemoryWriteForbiddenError,
)
from iam_sentinel_agents.tools.common.event_parser import (
    build_action_group_response,
    build_fallback_error_response,
    parse_action_group,
)
from iam_sentinel_agents.tools.memory import recall as recall_mod
from iam_sentinel_agents.tools.memory import remember as remember_mod

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

_logger = Logger(service="iam-sentinel-memory", level="INFO")
_tracer = Tracer(service="iam-sentinel-memory")
_metrics = Metrics(namespace=adapter_settings.metric_namespace, service="iam-sentinel-memory")


def _dispatch_recall(memory: MemoryClient, principal: str, params: dict[str, Any]) -> dict[str, Any]:
    kind = params.get("kind")
    if kind == "episodic":
        result = recall_mod.recall_episodic(
            memory,
            invoking_principal=principal,
            query=params.get("query"),
            top_k=int(params.get("top_k", 5)),
        )
    elif kind == "semantic":
        result = recall_mod.recall_semantic(
            memory,
            entity_kind=params.get("facet", {}).get("entity_kind", "") if params.get("facet") else "",
            facet=params.get("facet"),
        )
    elif kind == "procedural":
        result = recall_mod.recall_procedural(
            memory,
            pattern_kind=params.get("pattern_kind", ""),
            pattern_hash=params.get("pattern_hash", ""),
        )
    else:
        raise ContractError(f"unknown recall kind: {kind!r}")
    return result.model_dump(mode="json")


def _dispatch_remember(memory: MemoryClient, principal: str, params: dict[str, Any]) -> dict[str, Any]:
    kind = params.get("kind")
    record = params.get("record", {})
    writer_role = params.get("writer_role", "")
    if kind == "episodic":
        remember_mod.remember_episodic(
            memory,
            EpisodicMemory.model_validate(record),
            invoking_principal=principal,
            writer_role=writer_role,
        )
    elif kind == "semantic":
        remember_mod.upsert_semantic(memory, SemanticEntity.model_validate(record), writer_role=writer_role)
    elif kind == "procedural":
        remember_mod.remember_procedural(
            memory,
            pattern_kind=record.get("pattern_kind", ""),
            pattern_hash=record.get("pattern_hash", ""),
            result=record.get("result", {}),
            ttl_seconds=int(record.get("ttl", 900)),
            writer_role=writer_role,
        )
    else:
        raise ContractError(f"unknown remember kind: {kind!r}")
    return {"written": True}


@_metrics.log_metrics
@_tracer.capture_lambda_handler
def memory_actions_handler(event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """Single Lambda entrypoint for both `/recall` and `/remember`
    (`memory_actions.yaml`'s two `operationId`s route to the same
    function; Bedrock dispatch is keyed by `apiPath`, handled below).
    """
    try:
        invocation = parse_action_group(event)
    except ContractError as exc:
        _logger.warning("rejected_envelope", error=str(exc))
        _metrics.add_metric(name="SentinelMemoryRejected", unit=MetricUnit.Count, value=1)
        return build_fallback_error_response(event, http_status=400, message=str(exc))

    _logger.append_keys(correlation_id=invocation.correlation_id, api_path=invocation.api_path)
    _tracer.put_annotation(key="correlation_id", value=invocation.correlation_id)

    memory = MemoryClient()
    try:
        if invocation.api_path == "/recall":
            body = _dispatch_recall(memory, invocation.principal, invocation.parameters)
            _metrics.add_dimension(name="kind", value=str(invocation.parameters.get("kind")))
            _metrics.add_metric(name="SentinelMemoryReads", unit=MetricUnit.Count, value=1)
        elif invocation.api_path == "/remember":
            body = _dispatch_remember(memory, invocation.principal, invocation.parameters)
            _metrics.add_dimension(name="kind", value=str(invocation.parameters.get("kind")))
            _metrics.add_metric(name="SentinelMemoryWrites", unit=MetricUnit.Count, value=1)
        else:
            raise ContractError(f"unknown apiPath: {invocation.api_path!r}")
    except (MemoryIsolationError, MemoryWriteForbiddenError) as exc:
        _logger.warning("memory_access_denied", error=str(exc))
        _metrics.add_metric(name="SentinelMemoryAccessDenied", unit=MetricUnit.Count, value=1)
        return build_action_group_response(invocation, http_status=403, body={"error": str(exc)})
    except ContractError as exc:
        _logger.warning("memory_bad_request", error=str(exc))
        return build_action_group_response(invocation, http_status=400, body={"error": str(exc)})
    except Exception as exc:
        _logger.exception("memory_action_failed")
        return build_action_group_response(invocation, http_status=500, body={"error": str(exc)})
    finally:
        _logger.remove_keys(["correlation_id", "api_path"])

    return build_action_group_response(invocation, http_status=200, body=body)
