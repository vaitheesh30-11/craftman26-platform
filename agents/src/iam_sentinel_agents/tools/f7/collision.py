"""collision_resolve -- F7 Collision Resolver's one tool Lambda (phase-08 §2,
§4 Steps 1-5). Orchestrates `tools/f7/chain.walk_scp_chain` ->
`tools/common/scp_engine.compute_effective_policy` ->
`tools/common/scp_engine.find_collisions`, then renders each collision's
plain-English explanation (`plain_english.py`) and minimal fix
(`minimal_fix.py`) and assembles a `ScpCollisionPayload`.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from iam_sentinel_agents.contracts.scp_collision import ScpCollision, ScpCollisionPayload
from iam_sentinel_agents.tools.common import scp_engine
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f7 import chain as chain_module
from iam_sentinel_agents.tools.f7.minimal_fix import build_minimal_fix
from iam_sentinel_agents.tools.f7.plain_english import build_plain_english

if TYPE_CHECKING:
    import boto3
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_organizations.client import OrganizationsClient

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation


def _scp_chain_summary(levels: list[scp_engine.ScpLevelChain]) -> list[dict[str, object]]:
    return [
        {
            "level": level.level,
            "target_id": level.target_id,
            "policies": [
                {"policy_id": policy.policy_id, "name": policy.name, "arn": policy.arn}
                for policy in level.policies
            ],
        }
        for level in levels
    ]


def _build_collision(raw: dict[str, Any]) -> ScpCollision:
    fix = build_minimal_fix(
        action=raw["action"],
        denying_statement_id=raw["denying_statement_id"],
        denying_action_patterns=raw["denying_action_patterns"],
        denying_resource_patterns=raw["denying_resource_patterns"],
    )
    plain_english = build_plain_english(
        action=raw["action"],
        denying_scp_name=raw["denied_by_scp_name"],
        denying_level=raw["denied_at_level"],
        denying_statement_id=raw["denying_statement_id"],
        allowing_scp_name=raw["allowed_by_scp_name"],
        allowing_level=raw["allowed_at_level"],
    )
    return ScpCollision(
        action_pattern=raw["action"],
        resource_pattern=raw["resource_pattern"],
        allowed_by_scp_arn=raw["allowed_by_scp_arn"],
        allowed_at_level=raw["allowed_at_level"],
        denied_by_scp_arn=raw["denied_by_scp_arn"],
        denied_at_level=raw["denied_at_level"],
        denying_statement_id=raw["denying_statement_id"],
        plain_english=plain_english,
        minimal_fix=fix,
    )


def resolve_collisions(
    account_id: str,
    *,
    exclude_statement_ids: list[str] | None = None,
    organizations_client: OrganizationsClient | None = None,
    session: boto3.Session | None = None,
) -> ScpCollisionPayload:
    """Core orchestration, independent of the Bedrock Lambda envelope.

    `organizations_client`/`session` are injection points for tests (moto);
    production leaves both unset and lets `chain.walk_scp_chain` build its
    own client, per phase-08 §7 ("No cross-account role needed").
    """
    excluded = set(exclude_statement_ids or [])
    levels = chain_module.walk_scp_chain(
        account_id, organizations_client=organizations_client, session=session
    )
    result = scp_engine.compute_effective_policy(levels)
    raw_collisions = scp_engine.find_collisions(result["provenance"])

    collisions = [
        _build_collision(raw)
        for raw in raw_collisions
        # phase-08 §10 risk mitigation: operators mute collisions they
        # intended (`<trusted_input>.exclude_statement_ids`).
        if raw["denying_statement_id"] not in excluded
    ]

    return ScpCollisionPayload(
        account_id=account_id,
        scp_chain=_scp_chain_summary(levels),
        effective_policy=result["effective_policy"],
        collision_count=len(collisions),
        collisions=collisions,
        engine_version=scp_engine.ENGINE_VERSION,
    )


@sentinel_handler(feature_id="F7", tool_name="collision_resolve")
def collision_resolve(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    payload = resolve_collisions(
        invocation.parameters["account_id"],
        exclude_statement_ids=invocation.parameters.get("exclude_statement_ids"),
    )
    return payload.model_dump(mode="json")
