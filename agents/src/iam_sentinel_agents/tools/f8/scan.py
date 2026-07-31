"""slr_scan -- evaluate a proposed SCP against every curated SLR row
(phase-09 §4 Steps 3-5). `evaluate_scp` is pure computation over its two
arguments (no AWS calls); the Lambda handler below is the only place that
reaches DynamoDB, via `iam_sentinel_adapters.ddb.slrs.SlrsClient` -- the
project's boto3-only-through-adapters boundary (agents/README.md §1),
unlike F1's IAM-read exception (no adapter wraps IAM read APIs; one does
wrap DynamoDB, so this tool uses it, per ADR 0006's "add on-demand per
consumer" precedent).
"""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from typing import Any, TYPE_CHECKING

from iam_sentinel_adapters.ddb.slrs import SlrsClient

from iam_sentinel_agents.contracts.slr import SlrImpactPayload
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f8.actions import (
    build_action_universe,
    expand_action_patterns,
    normalize_actions,
)
from iam_sentinel_agents.tools.f8.exemptions import (
    apply_exemptions,
    strategy_a_condition,
    strategy_b_condition,
)
from iam_sentinel_agents.tools.f8.impact import classify_impact

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

# phase-09 §4 Step 5: "If > 5,000 bytes: exceeds_size_limit=true."
_SAFE_SCP_SIZE_LIMIT_BYTES = 5_000
_UNKNOWN_DB_VERSION = "unknown"


def _normalize_statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    statement = document.get("Statement", [])
    return [statement] if isinstance(statement, dict) else list(statement)


def _canonical_bytes(document: dict[str, Any]) -> int:
    return len(json.dumps(document, separators=(",", ":")))


def evaluate_scp(proposed_scp: dict[str, Any], slr_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Core scan logic (phase-09 §4 Steps 3-5). Returns a plain dict shaped
    exactly like `SlrImpactPayload` -- callers that need the validated
    model call `SlrImpactPayload.model_validate(...)` on the result.
    """
    safe_scp = copy.deepcopy(proposed_scp)
    statements = _normalize_statements(safe_scp)
    safe_scp["Statement"] = statements

    universe = build_action_universe(slr_rows)

    conflicts: list[dict[str, Any]] = []
    conflicting_principals_by_statement: dict[int, set[str]] = defaultdict(set)

    for index, statement in enumerate(statements):
        if statement.get("Effect") != "Deny":
            continue
        expanded = expand_action_patterns(normalize_actions(statement.get("Action", [])), universe)
        if not expanded:
            continue
        expanded_lowered = set(expanded)

        for row in slr_rows:
            required_lower_to_original = {
                str(action).lower(): str(action) for action in row.get("required_actions", [])
            }
            intersection_lower = expanded_lowered & required_lower_to_original.keys()
            if not intersection_lower:
                continue

            core_lower = {str(action).lower() for action in row.get("core_actions", [])}
            impact = classify_impact(
                intersection_count=len(intersection_lower),
                required_count=len(required_lower_to_original),
                core_hit=bool(intersection_lower & core_lower),
            )
            service_principal = str(row["service_principal"])
            conflicting_principals_by_statement[index].add(service_principal)
            conflicts.append(
                {
                    "service_principal": service_principal,
                    "slr_name": row["slr_name"],
                    "blocked_actions": sorted(
                        required_lower_to_original[action] for action in intersection_lower
                    ),
                    "impact": impact,
                    "proposed_exemption_statement": strategy_a_condition(service_principal),
                    "alternative_condition": strategy_b_condition(),
                }
            )

    for index, service_principals in conflicting_principals_by_statement.items():
        apply_exemptions(statements[index], sorted(service_principals))

    slr_db_version = str(slr_rows[0]["db_version"]) if slr_rows else _UNKNOWN_DB_VERSION
    safe_scp_bytes = _canonical_bytes(safe_scp)

    return {
        "proposed_scp": proposed_scp,
        "proposed_scp_bytes": _canonical_bytes(proposed_scp),
        "slr_db_version": slr_db_version,
        "total_slrs_checked": len(slr_rows),
        "conflicts": conflicts,
        "safe_scp": safe_scp,
        "safe_scp_bytes": safe_scp_bytes,
        "exceeds_size_limit": safe_scp_bytes > _SAFE_SCP_SIZE_LIMIT_BYTES,
    }


@sentinel_handler(feature_id="F8", tool_name="slr_scan")
def slr_scan(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    proposed_scp = invocation.parameters["proposed_scp"]
    slr_rows = SlrsClient().list_all()
    payload = evaluate_scp(proposed_scp, slr_rows)
    return SlrImpactPayload.model_validate(payload).model_dump(mode="json")
