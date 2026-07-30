"""15-second-wait + 3-poll IAM eventual-consistency verification (phase-02
§5 step 3).

Split from `client.py` so the polling/comparison logic can be unit-tested
without a real `ZelkovaClient` -- it takes its dependencies (the IAM client,
the `check_no_new_access` callable, and even `sleep`) as plain arguments.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json
from iam_sentinel_adapters.zelkova.models import PolicyPair, Witness, ZelkovaResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from iam_sentinel_adapters.evidence.keys import FeatureID

_POLL_INTERVAL_SECONDS = 5.0


def run_post_check(
    *,
    role_arn: str,
    policy_name: str,
    expected_policy: dict[str, Any],
    wait_seconds: int,
    max_polls: int,
    correlation_id: str,
    feature_id: FeatureID,
    iam_client: Any,
    check_no_new_access: Callable[..., ZelkovaResult],
    sleep: Callable[[float], None] = time.sleep,
) -> ZelkovaResult:
    sleep(wait_seconds)

    role_name = role_arn.rsplit("/", 1)[-1]
    expected_hash = _sha256(expected_policy)
    start = time.monotonic()

    observed: dict[str, Any] | None = None
    observed_hash = ""
    for attempt in range(max_polls):
        observed = _fetch_policy(iam_client, role_name=role_name, policy_name=policy_name)
        if observed is not None:
            observed_hash = _sha256(observed)
            if observed_hash == expected_hash:
                break
        if attempt < max_polls - 1:
            sleep(_POLL_INTERVAL_SECONDS)

    latency_ms = int((time.monotonic() - start) * 1000) + wait_seconds * 1000

    if observed is None or observed_hash != expected_hash:
        return ZelkovaResult(
            pass_=False,
            result="FAIL",
            witness=Witness(
                principal=role_arn,
                context={"reason": "post_check_mismatch", "polls_exhausted": max_polls},
            ),
            latency_ms=latency_ms,
            invoked_at=datetime.now(UTC),
            policy_pair=PolicyPair(
                existing=expected_policy,
                candidate=observed or {},
                existing_sha256=expected_hash,
                candidate_sha256=observed_hash,
            ),
        )

    # Defends against a race where a third party edited the policy in the
    # same window (phase-02 §5 step 3) -- the byte-match above only proves
    # IAM converged to *some* candidate; this proves it's still safe.
    race_result = check_no_new_access(
        existing=expected_policy,
        candidate=observed,
        correlation_id=correlation_id,
        feature_id=feature_id,
    )
    return ZelkovaResult(
        pass_=race_result.pass_,
        result=race_result.result,
        witness=race_result.witness,
        latency_ms=latency_ms + race_result.latency_ms,
        invoked_at=race_result.invoked_at,
        policy_pair=race_result.policy_pair,
    )


def _fetch_policy(iam_client: Any, *, role_name: str, policy_name: str) -> dict[str, Any] | None:
    try:
        response = iam_client.get_role_policy(RoleName=role_name, PolicyName=policy_name)
    except iam_client.exceptions.NoSuchEntityException:
        return None
    return dict(response["PolicyDocument"])


def _sha256(policy: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_json(policy).encode("utf-8")).hexdigest()
