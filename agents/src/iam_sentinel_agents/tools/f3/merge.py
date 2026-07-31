"""data_event_merge — phase-04 §4 Step 6 (deep-merge + dedupe + byte cap)
plus the SAFETY clause's wildcard rejection.

Pure computation over its inputs -- no AWS calls, matching phase-04 §3's
tool-contract summary for this one (unlike `ensure_logging`/`query`, this
tool's summary and its algorithm agree).
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from iam_sentinel_agents.contracts.data_event import S3DataEventUsage
from iam_sentinel_agents.tools.common.runtime import sentinel_handler

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

_INLINE_POLICY_BYTE_CAP = 6_144
_FORBIDDEN_WILDCARD_ACTIONS = frozenset({"s3:*", "*"})


def _statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    statement = document.get("Statement", [])
    return [statement] if isinstance(statement, dict) else list(statement)


def _has_forbidden_wildcard(statements: list[dict[str, Any]]) -> bool:
    """SAFETY clause: never `Action: "s3:*"` or `Resource: "*"`.

    `"*" in resources` is a list-membership check against the exact string
    `"*"` -- a scoped ARN like `"arn:aws:s3:::bucket/*"` never matches this,
    only a literal bare wildcard resource does.
    """
    for statement in statements:
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        if any(str(action) in _FORBIDDEN_WILDCARD_ACTIONS for action in actions):
            return True
        resources = statement.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]
        if "*" in resources:
            return True
    return False


def _statement_for(usage: S3DataEventUsage) -> dict[str, Any] | None:
    if not usage.consolidated_prefix:
        return None
    resource = f"arn:aws:s3:::{usage.bucket}/{usage.consolidated_prefix}"
    return {"Effect": "Allow", "Action": usage.action, "Resource": resource}


def _dedupe_and_group(new_statements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Phase-04 §4 Step 6: "Group by (Effect, Action set): a Statement can
    have `Action` as list and `Resource` as list when all elements share
    the same Effect and match the same wildcard shape." Grouped by
    (Effect, Action) here since every statement this module constructs has
    exactly one Action (from `S3DataEventUsage.action`) -- the "Action set"
    case only arises once multiple usage rows share one bucket+prefix+action,
    which this groups into one Resource list (or bare string) instead.
    """
    grouped: dict[tuple[str, str], set[str]] = {}
    order: list[tuple[str, str]] = []
    for statement in new_statements:
        key = (statement["Effect"], statement["Action"])
        if key not in grouped:
            grouped[key] = set()
            order.append(key)
        grouped[key].add(statement["Resource"])

    result: list[dict[str, Any]] = []
    for effect, action in order:
        resources = sorted(grouped[(effect, action)])
        resource_value: Any = resources[0] if len(resources) == 1 else resources
        result.append({"Effect": effect, "Action": action, "Resource": resource_value})
    return result


def merge_policy(base_policy: dict[str, Any], usage: list[S3DataEventUsage]) -> dict[str, Any]:
    """Returns `{"merged_policy", "merged_policy_bytes", "truncated"}`.

    `truncated=True` collapses the artifact back to `base_policy` alone
    (no data-event statements attached) for two distinct reasons the phase
    doc treats identically (§4 Step 6, §9, SAFETY): the merge exceeded the
    6,144-byte inline cap, OR it would have emitted a forbidden wildcard.
    Either way there is no safe artifact to hand a human -- downgrading the
    Finding to REQUIRES_HUMAN is the specialist prompt's job, not this
    tool's; this tool only ever reports the fact via `truncated`.
    """
    base_statements = _statements(base_policy)
    candidate_new = [
        statement
        for statement in (_statement_for(entry) for entry in usage)
        if statement is not None
    ]
    merged_new = _dedupe_and_group(candidate_new)
    merged_statements = [*base_statements, *merged_new]

    if _has_forbidden_wildcard(merged_statements):
        fallback_policy = {
            "Version": base_policy.get("Version", "2012-10-17"),
            "Statement": base_statements,
        }
        return {
            "merged_policy": fallback_policy,
            "merged_policy_bytes": len(json.dumps(fallback_policy, separators=(",", ":"))),
            "truncated": True,
        }

    merged_policy = {
        "Version": base_policy.get("Version", "2012-10-17"),
        "Statement": merged_statements,
    }
    merged_bytes = len(json.dumps(merged_policy, separators=(",", ":")))
    return {
        "merged_policy": merged_policy,
        "merged_policy_bytes": merged_bytes,
        "truncated": merged_bytes > _INLINE_POLICY_BYTE_CAP,
    }


@sentinel_handler(feature_id="F3", tool_name="data_event_merge")
def data_event_merge(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    usage = [S3DataEventUsage.model_validate(raw) for raw in invocation.parameters.get("usage", [])]
    return merge_policy(invocation.parameters["base_policy"], usage)
