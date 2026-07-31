"""session_kill_cleanup — TTL-driven inline-policy removal (phase-06 §4
Step 4), triggered by an EventBridge `rate(1 minute)` schedule.

"If a NEW revocation exists for the same (account, role) before cleanup
ran, EXTEND ttl_expires_at instead of cleaning -- never remove a live
revocation" is implemented via the single-item-per-`(account_id, role_arn)`
key `RevocationsClient` already establishes (docs/decisions/0023): a fresh
dispatch on the same role overwrites the DDB item forward with a later
`ttl_expires_at` and a new `revocation_policy_name`. `run_cleanup` re-reads
each expired candidate immediately before deleting; if the live item no
longer matches the snapshot it queried (a newer dispatch already
superseded it), it skips that item entirely -- the record has effectively
already been "extended" by the overwrite, so there is nothing left to
clean for it. The consequence, documented rather than silently accepted:
the *superseded* policy's own `PolicyName` (the old
`SENTINEL_EMERGENCY_REVOKE_*` inline statement in IAM) is never explicitly
deleted once superseded, because the DDB row no longer carries its name.
This is harmless, not just deferred: every emergency Deny is a
`DateLessThan` condition on `aws:TokenIssueTime`, so an orphaned older
(earlier-cutoff) Deny denies a *subset* of what the newer, later-cutoff
Deny already denies -- it can never re-permit anything the newer policy
blocks, and it expires out of relevance once no session predates its own
cutoff.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

from iam_sentinel_adapters.ddb.revocations import RevocationsClient
from iam_sentinel_adapters.sns.client import SnsClient

from iam_sentinel_agents.tools.common import cross_account

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

    from iam_sentinel_agents.contracts.common import FeatureID


def _still_expired_and_unclaimed(revocations: RevocationsClient, candidate: dict[str, Any]) -> bool:
    live = revocations.get(candidate["account_id"], candidate["role_arn"])
    if live is None:
        return False
    return live.get("revocation_policy_name") == candidate.get(
        "revocation_policy_name"
    ) and not live.get("cleaned", False)


def run_cleanup(
    *,
    now: datetime | None = None,
    feature_id: FeatureID = "F5",
    correlation_id: str = "f5-ttl-cleanup",
    revocations_client: RevocationsClient | None = None,
    sns_client: SnsClient | None = None,
    cross_account_assume: Any = cross_account.assume,
) -> dict[str, Any]:
    revocations = revocations_client or RevocationsClient()
    sns = sns_client or SnsClient()
    resolved_now = now or datetime.now(UTC)

    cleaned: list[str] = []
    extended: list[str] = []

    for candidate in revocations.query_expired(resolved_now):
        account_id = candidate["account_id"]
        role_arn = candidate["role_arn"]

        if not _still_expired_and_unclaimed(revocations, candidate):
            extended.append(role_arn)
            continue

        role_name = role_arn.split("/")[-1]
        policy_name = candidate["revocation_policy_name"]
        session = cross_account_assume(
            account_id, feature_id=feature_id, correlation_id=correlation_id
        )
        iam = session.client("iam")
        with contextlib.suppress(iam.exceptions.NoSuchEntityException):
            # already gone -- still confirmed absent, proceed to mark cleaned
            iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)

        try:
            iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
        except iam.exceptions.NoSuchEntityException:
            pass
        else:
            # Deletion did not take: leave `cleaned=false` so the next
            # 1-minute sweep retries rather than silently declaring victory.
            continue

        revocations.mark_cleaned(account_id, role_arn, cleaned_at=resolved_now)
        cleaned.append(role_arn)
        sns.publish_critical_finding(
            subject="F5 emergency revocation expired",
            message=(
                f"Emergency revocation expired, access restored, "
                f"correlation_id={candidate.get('correlation_id', 'unknown')}."
            ),
        )

    return {"cleaned": cleaned, "extended": extended}


def session_kill_cleanup(_event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """EventBridge `rate(1 minute)` scheduled-rule entrypoint -- no Bedrock
    envelope, so `sentinel_handler` doesn't apply here either.
    """
    return run_cleanup()
