"""session_kill_dispatch — F5 discovery + fan-out (phase-06 §4 Step 2).

Deliberate deviation, documented in docs/decisions/0023: the spec's own
Step 2 reuses one `revocation_policy_name` (unique per invocation) as
every fanned-out message's `MessageDeduplicationId`. SQS FIFO dedup is
scoped to the whole queue, not per `MessageGroupId` -- reusing one
dedup id across N different messages inside the same 5-minute dedup
window means SQS treats messages 2..N as duplicates of message 1 and
silently drops them, defeating the fan-out entirely. This module scopes
`MessageDeduplicationId` to `{revocation_policy_name}#{account_id}#{role_arn}`
instead: still unique per invocation, still traceable back to the
revocation, but unique per message the way FIFO dedup actually requires.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, UTC
from fnmatch import fnmatchcase
from typing import Any, TYPE_CHECKING

from iam_sentinel_adapters.ddb.revocations import RevocationsClient
from iam_sentinel_adapters.sqs.client import SqsClient

from iam_sentinel_agents.contracts.session_kill import (
    SessionKillPayload,
    TerminationRecord,
    TriggerSource,
)
from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f5 import discovery
from iam_sentinel_agents.tools.f5.denylist import is_denylisted, load_never_revoke_patterns

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_sso_admin.client import SSOAdminClient

    from iam_sentinel_agents.contracts.common import FeatureID
    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

# phase-06 §10 risk mitigation: a false-positive GuardDuty finding must not
# trigger a long-lived revocation storm.
_GUARDDUTY_TTL_CAP_SECONDS = 900
_SSO_ROLE_PATH_PREFIX = "/aws-reserved/sso.amazonaws.com/"


def _capped_ttl_seconds(ttl_seconds: int, trigger_source: TriggerSource) -> int:
    if trigger_source == "guardduty":
        return min(ttl_seconds, _GUARDDUTY_TTL_CAP_SECONDS)
    return min(ttl_seconds, 14_400)


def _sso_role_arns_for(
    account_id: str, permission_set_name: str, *, feature_id: FeatureID, correlation_id: str
) -> list[str]:
    session = cross_account.assume(account_id, feature_id=feature_id, correlation_id=correlation_id)
    iam = session.client("iam")
    pattern = f"AWSReservedSSO_{permission_set_name}_*"
    matches: list[str] = []
    for page in iam.get_paginator("list_roles").paginate(PathPrefix=_SSO_ROLE_PATH_PREFIX):
        for role in page["Roles"]:
            if fnmatchcase(role["RoleName"], pattern):
                matches.append(role["Arn"])
    return matches


def dispatch(
    *,
    permission_set_arn: str,
    principal_arn: str | None,
    ttl_seconds: int,
    reason: str,
    trigger_source: TriggerSource,
    correlation_id: str,
    sso_client: SSOAdminClient,
    sqs_client: SqsClient | None = None,
    revocations_client: RevocationsClient | None = None,
    denylist_patterns: list[str] | None = None,
) -> SessionKillPayload:
    sqs = sqs_client or SqsClient()
    revocations = revocations_client or RevocationsClient()
    patterns = denylist_patterns if denylist_patterns is not None else load_never_revoke_patterns()

    capped_ttl = _capped_ttl_seconds(ttl_seconds, trigger_source)
    instance_arn = discovery.resolve_instance_arn(sso_client)
    permission_set_name = discovery.describe_permission_set_name(
        sso_client, instance_arn=instance_arn, permission_set_arn=permission_set_arn
    )
    assignments = discovery.list_assignments(
        sso_client,
        instance_arn=instance_arn,
        permission_set_arn=permission_set_arn,
        principal_arn=principal_arn,
    )
    account_ids = sorted({a["AccountId"] for a in assignments})

    now = datetime.now(UTC)
    ttl_expires_at = now + timedelta(seconds=capped_ttl)
    revocation_policy_name = f"SENTINEL_EMERGENCY_REVOKE_{int(time.time())}"

    terminations: list[TerminationRecord] = []
    accounts_failed: list[str] = []

    for account_id in account_ids:
        try:
            role_arns = _sso_role_arns_for(
                account_id,
                permission_set_name,
                feature_id="F5",
                correlation_id=correlation_id,
            )
        except Exception:  # noqa: BLE001 -- a single account's discovery failure must not abort the fan-out
            accounts_failed.append(account_id)
            continue

        for role_arn in role_arns:
            if is_denylisted(role_arn, patterns):
                continue

            record = TerminationRecord(
                account_id=account_id,
                role_arn=role_arn,
                revocation_policy_name=revocation_policy_name,
                token_issue_time_cutoff=now,
                attached_at=now,
                ttl_expires_at=ttl_expires_at,
                verify_attempts=0,
                verified_attached=False,
            )
            revocations.put(
                {
                    **record.model_dump(mode="json"),
                    "correlation_id": correlation_id,
                    "cleaned": False,
                    "reason": reason,
                }
            )
            message_body = {
                "account_id": account_id,
                "role_arn": role_arn,
                "token_issue_time_cutoff": record.token_issue_time_cutoff.isoformat(),
                "ttl_expires_at": record.ttl_expires_at.isoformat(),
                "revocation_policy_name": revocation_policy_name,
                "correlation_id": correlation_id,
            }
            sqs.send_fifo_message(
                message_group_id=account_id,
                deduplication_id=f"{revocation_policy_name}#{account_id}#{role_arn}",
                body=json.dumps(message_body, separators=(",", ":")),
            )
            terminations.append(record)

    return SessionKillPayload(
        trigger_source=trigger_source,
        principal_arn=principal_arn,
        permission_set_arn=permission_set_arn,
        reason=reason,
        ttl_seconds=capped_ttl,
        accounts_targeted=len(account_ids),
        accounts_completed=0,
        accounts_failed=accounts_failed,
        terminations=terminations,
        correlation_id=correlation_id,
    )


@sentinel_handler(feature_id="F5", tool_name="session_kill_dispatch")
def session_kill_dispatch(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    import boto3

    from iam_sentinel_agents.settings import settings

    sso_client = boto3.client("sso-admin", region_name=settings.region)
    payload = dispatch(
        permission_set_arn=invocation.parameters["permission_set_arn"],
        principal_arn=invocation.parameters.get("principal_arn"),
        ttl_seconds=int(invocation.parameters["ttl_seconds"]),
        reason=invocation.parameters["reason"],
        trigger_source=invocation.parameters["trigger_source"],
        correlation_id=invocation.correlation_id,
        sso_client=sso_client,
    )
    return payload.model_dump(mode="json")
