"""base_policy_generate + Zelkova pre-check helper — phase-04 §4 Steps 5, 7.

Not an action-group tool: §3's "Tool contracts" section lists only
`data_event_ensure_logging`, `data_event_query`, `data_event_merge` — the
specialist prompt's WORKFLOW step 3 calls `StartPolicyGeneration`/poll "via
a base_policy_generate helper wired through the runtime", the same shape as
F1's `graph.build_blast_payload` (agents phase-02): a pure-Python function
tests can exercise directly. Whatever Lambda actually orchestrates a full
specialist turn end-to-end (Prime's supervisor / phase-01) is this helper's
real caller — not built in this phase.

Uses `iam_sentinel_adapters.zelkova.ZelkovaClient` for every
StartPolicyGeneration/GetGeneratedPolicy/CheckNoNewAccess call — that
adapter already exists (adapters phase-02) and wraps exactly these three
APIs with retry/breaker/evidence/cost-meter behavior; this module does not
reinvent that surface.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from iam_sentinel_agents.contracts.data_event import DataEventPolicyPayload, S3DataEventUsage
from iam_sentinel_agents.contracts.remediation import ZelkovaCheck

if TYPE_CHECKING:
    from collections.abc import Callable

    from iam_sentinel_adapters.zelkova.client import ZelkovaClient
    from iam_sentinel_adapters.zelkova.models import ZelkovaResult

    from iam_sentinel_agents.contracts.common import FeatureID

_POLL_INTERVAL_SECONDS = 5.0
_MAX_WAIT_SECONDS = 300.0
_EMPTY_POLICY: dict[str, Any] = {"Version": "2012-10-17", "Statement": []}


class PolicyGenerationTimeoutError(RuntimeError):
    """Raised when `GetGeneratedPolicy` never leaves `IN_PROGRESS` within
    the 5-minute budget phase-04 §4 Step 5 allots.
    """


def generate_base_policy(
    *,
    role_arn: str,
    cloudtrail_details: dict[str, Any],
    zelkova: ZelkovaClient,
    correlation_id: str,
    feature_id: FeatureID = "F3",
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """§4 Step 5: `StartPolicyGeneration` + poll `GetGeneratedPolicy` every
    5s up to 5 minutes.
    """
    job_id = zelkova.start_policy_generation(
        principal_arn=role_arn,
        cloudtrail_details=cloudtrail_details,
        correlation_id=correlation_id,
        feature_id=feature_id,
    )
    elapsed = 0.0
    while elapsed <= _MAX_WAIT_SECONDS:
        policy = zelkova.get_generated_policy(
            job_id=job_id, correlation_id=correlation_id, feature_id=feature_id
        )
        if policy is not None:
            return policy
        sleep(_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS
    raise PolicyGenerationTimeoutError(
        f"policy generation job {job_id!r} did not complete within 5 minutes"
    )


def zelkova_precheck(
    *,
    base_policy: dict[str, Any],
    merged_policy: dict[str, Any],
    zelkova: ZelkovaClient,
    correlation_id: str,
    feature_id: FeatureID = "F3",
) -> ZelkovaCheck:
    """§4 Step 7's two `CheckNoNewAccess` calls.

    Check 1 (baseline=empty, candidate=base_policy) establishes what the
    role already legitimately does per Access Analyzer's own generated
    policy; check 2 (baseline=base_policy, candidate=merged_policy) is the
    one that gates the artifact and is what
    `DataEventPolicyPayload.zelkova_pre` persists. Check 1's result has no
    corresponding contract field — it still runs (for its evidence + cost-
    meter side effects via `ZelkovaClient`) but its `ZelkovaResult` is
    discarded here, matching the phase doc's own framing ("gives baseline
    grants" — informational, not a gate).
    """
    zelkova.check_no_new_access(
        existing=_EMPTY_POLICY,
        candidate=base_policy,
        correlation_id=correlation_id,
        feature_id=feature_id,
    )
    result = zelkova.check_no_new_access(
        existing=base_policy,
        candidate=merged_policy,
        correlation_id=correlation_id,
        feature_id=feature_id,
    )
    return _to_zelkova_check(result)


def _to_zelkova_check(result: ZelkovaResult) -> ZelkovaCheck:
    pair = result.policy_pair
    return ZelkovaCheck(
        **{"pass": result.pass_},
        witness=_witness_repr(result),
        latency_ms=result.latency_ms,
        invoked_at=result.invoked_at,
        baseline_hash=pair.existing_sha256 if pair is not None else "0" * 64,
        candidate_hash=pair.candidate_sha256 if pair is not None else "0" * 64,
    )


def _witness_repr(result: ZelkovaResult) -> str | None:
    witness = result.witness
    if witness is None:
        return None
    parts = " ".join(part for part in (witness.principal, witness.action, witness.resource) if part)
    return parts or None


def build_data_event_payload(
    *,
    role_arn: str,
    days_back: int,
    base_policy: dict[str, Any],
    usage: list[S3DataEventUsage],
    merge_result: dict[str, Any],
    zelkova_pre: ZelkovaCheck,
) -> DataEventPolicyPayload:
    return DataEventPolicyPayload(
        role_arn=role_arn,
        days_back=days_back,
        base_policy=base_policy,
        data_event_usage=usage,
        merged_policy=merge_result["merged_policy"],
        merged_policy_bytes=merge_result["merged_policy_bytes"],
        truncated=merge_result["truncated"],
        zelkova_pre=zelkova_pre,
    )
