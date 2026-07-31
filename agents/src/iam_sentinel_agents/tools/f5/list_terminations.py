"""list_terminations — action-group tool the specialist polls (phase-06 §5
WORKFLOW step 3: "Poll DDB via list_terminations tool until
accounts_completed == accounts_targeted OR a 60s window closes").

Reads `SentinelRevocations` by `correlation_id` via the `correlation-index`
GSI (aws-infra's `foundation_stack.py`) rather than the payload dispatch
returned, since dispatch and the eventual worker completions are separate
Lambda invocations with no shared memory.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from iam_sentinel_adapters.ddb.revocations import RevocationsClient

from iam_sentinel_agents.tools.common.runtime import sentinel_handler

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation


def list_terminations_for(
    correlation_id: str, *, revocations_client: RevocationsClient | None = None
) -> dict[str, Any]:
    revocations = revocations_client or RevocationsClient()
    items = revocations.query_by_correlation_id(correlation_id)
    completed = sum(1 for item in items if item.get("verified_attached"))
    return {
        "correlation_id": correlation_id,
        "accounts_targeted": len(items),
        "accounts_completed": completed,
        "terminations": items,
    }


@sentinel_handler(feature_id="F5", tool_name="list_terminations")
def list_terminations(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    return list_terminations_for(invocation.parameters["correlation_id"])
