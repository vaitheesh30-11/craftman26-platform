"""Deterministic fast-path mirrors (agents phase-15 §2/§6 Step 2) for F1, F4,
F5, F7, F8 -- the specialists the spec names explicitly ("largely
computation, not reasoning") -- plus thin mirrors for F2, F3, F6 so
`functions/router.py` can satisfy every target `backend.RouterBridgeService`
already dispatches (`docs/decisions` for this phase's own ADR explains why
that superset is in scope). Every mirror composes the *same* core function
its Bedrock-envelope tool Lambda already calls (`tools/f1/scan.scan_account`,
`tools/f4/simulate.simulate`, ...) -- zero LLM tokens, same computation.

`AmbiguityError` is §6 Step 2's escalation contract: "if any tool returns a
hint (ambiguous=true...), the fast path escalates ... returns
RoutingDecision(mode='slow', fallback_target=<same feature>)". None of the
underlying tool functions natively emit an `ambiguous` flag (they were built
before this phase existed), so each mirror below defines its own concrete,
documented ambiguity condition -- a case where a crisp deterministic verdict
would be misleading and narrative synthesis is genuinely required.
"""

from __future__ import annotations

from typing import Any, cast, TYPE_CHECKING

from iam_sentinel_adapters.ddb.slrs import SlrsClient

from iam_sentinel_agents.errors import SentinelAgentError
from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.common.scp_policy_evaluator import LevelPolicies
from iam_sentinel_agents.tools.f1.scan import scan_account
from iam_sentinel_agents.tools.f2.classify import scan_and_classify
from iam_sentinel_agents.tools.f3.query import query_data_events
from iam_sentinel_agents.tools.f4.simulate import simulate
from iam_sentinel_agents.tools.f5.dispatch import dispatch as session_kill_dispatch
from iam_sentinel_agents.tools.f6.report import build_report, load_recent_violations
from iam_sentinel_agents.tools.f7.collision import resolve_collisions
from iam_sentinel_agents.tools.f8.scan import evaluate_scp

if TYPE_CHECKING:
    import boto3
    from iam_sentinel_adapters.ddb.findings import FindingsClient
    from mypy_boto3_athena.client import AthenaClient
    from mypy_boto3_sso_admin.client import SSOAdminClient

    from iam_sentinel_agents.contracts.common import Severity

# §6 Step 2 ambiguity thresholds -- each one documented at its call site.
_F1_MAX_UNFILTERED_PRINCIPALS = 1
_F7_MAX_COLLISIONS_BEFORE_ESCALATION = 5


class AmbiguityError(SentinelAgentError):
    """Raised by a fast-path mirror when it cannot produce a trustworthy
    deterministic verdict. `RequestRouter`/`functions/router.py` catches
    this and escalates to the slow path (§6 Step 2).
    """


def passrole_fast(
    payload: dict[str, Any], *, correlation_id: str, session: boto3.Session | None = None
) -> dict[str, Any]:
    account_id = str(payload["account_id"])
    principal_arn = payload.get("principal_arn")
    result = scan_account(
        account_id,
        principal_arn,
        feature_id="F1",
        correlation_id=correlation_id,
        session=session,
    )
    edges = result["edges"]
    distinct_principals = {edge["from_principal"] for edge in edges}
    if principal_arn is None and len(distinct_principals) > _F1_MAX_UNFILTERED_PRINCIPALS:
        raise AmbiguityError(
            f"{len(distinct_principals)} distinct principals hold PassRole grants in "
            f"{account_id} with no principal_arn filter; prioritizing them needs narrative "
            "synthesis, not a single deterministic verdict"
        )
    verdict = "CONFIRM" if edges else "REJECT"
    reason = (
        f"{len(edges)} PassRole grant(s) found across {result['principals_scanned']} "
        f"principal(s) scanned"
        if edges
        else f"no PassRole grants found across {result['principals_scanned']} principal(s) scanned"
    )
    return {"verdict": verdict, "reason": reason, "findings": edges, "remediation": None}


def scp_impact_fast(payload: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
    del correlation_id  # simulate() is pure; no cross-account call to trace
    chain = [LevelPolicies.model_validate(raw) for raw in payload["chain"]]
    proposed_scp = payload["proposed_scp"]
    history = list(payload.get("history", []))
    mode = str(payload.get("mode", "add"))

    result = simulate(chain=chain, proposed_scp=proposed_scp, history=history, mode=mode)
    blocked = result["impacted_roles"]
    if any(invocation.denying_statement_id is None for invocation in blocked):
        raise AmbiguityError(
            "at least one blocked invocation has no identifiable denying statement id; "
            "explaining why it's blocked needs reasoning"
        )
    verdict = "CONFIRM" if blocked else "REJECT"
    reason = (
        f"{result['calls_that_would_be_blocked']} of {result['total_calls_analyzed']} "
        "analyzed calls would be blocked by the proposed SCP"
    )
    remediation = (
        {"suggested_exemptions": [e.model_dump(mode="json") for e in result["suggested_exemptions"]]}
        if result["suggested_exemptions"]
        else None
    )
    return {
        "verdict": verdict,
        "reason": reason,
        "findings": [invocation.model_dump(mode="json") for invocation in blocked],
        "remediation": remediation,
    }


def emergency_kill_fast(
    payload: dict[str, Any],
    *,
    correlation_id: str,
    sso_client: SSOAdminClient,
) -> dict[str, Any]:
    """No `AmbiguityError` path: §4's policy row calls this route
    "Fast+audit" unconditionally -- F5's own dispatcher is deterministic
    fan-out with no interpretation step, so there is nothing to escalate.
    """
    result = session_kill_dispatch(
        permission_set_arn=str(payload["permission_set_arn"]),
        principal_arn=payload.get("principal_arn"),
        ttl_seconds=int(payload["ttl_seconds"]),
        reason=str(payload["reason"]),
        trigger_source=payload["trigger_source"],
        correlation_id=correlation_id,
        sso_client=sso_client,
    )
    verdict = "CONFIRM" if result.terminations else "INCONCLUSIVE"
    reason = (
        f"dispatched revocation across {result.accounts_targeted} account(s), "
        f"{len(result.terminations)} role session(s) targeted, "
        f"{len(result.accounts_failed)} account(s) failed discovery"
    )
    return {
        "verdict": verdict,
        "reason": reason,
        "findings": [t.model_dump(mode="json") for t in result.terminations],
        "remediation": {
            "accounts_targeted": result.accounts_targeted,
            "accounts_failed": result.accounts_failed,
        },
    }


def scp_collision_fast(
    payload: dict[str, Any], *, correlation_id: str, session: boto3.Session | None = None
) -> dict[str, Any]:
    del correlation_id  # resolve_collisions traces via its own boto3 calls, not this wrapper
    account_id = str(payload["account_id"])
    exclude = payload.get("exclude_statement_ids")
    result = resolve_collisions(account_id, exclude_statement_ids=exclude, session=session)
    if result.collision_count > _F7_MAX_COLLISIONS_BEFORE_ESCALATION:
        raise AmbiguityError(
            f"{result.collision_count} SCP collisions found in {account_id}; explaining that "
            "many overlapping denies coherently needs narrative synthesis"
        )
    verdict = "CONFIRM" if result.collisions else "REJECT"
    reason = f"{result.collision_count} SCP collision(s) found in {account_id}"
    return {
        "verdict": verdict,
        "reason": reason,
        "findings": [c.model_dump(mode="json") for c in result.collisions],
        "remediation": None,
    }


def slr_scan_fast(payload: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
    del correlation_id  # evaluate_scp is pure; SlrsClient.list_all() has its own retry/trace path
    proposed_scp = payload["proposed_scp"]
    slr_rows = SlrsClient().list_all()
    result = evaluate_scp(proposed_scp, slr_rows)
    if result["exceeds_size_limit"]:
        raise AmbiguityError(
            "safe_scp exceeds the 5,000-byte SCP size limit after applying exemptions; "
            "deciding how to shrink it needs reasoning"
        )
    verdict = "CONFIRM" if result["conflicts"] else "REJECT"
    reason = f"{len(result['conflicts'])} SLR conflict(s) found against {result['total_slrs_checked']} SLR(s)"
    remediation = {"safe_scp": result["safe_scp"]} if result["conflicts"] else None
    return {
        "verdict": verdict,
        "reason": reason,
        "findings": result["conflicts"],
        "remediation": remediation,
    }


def org_context_fast(
    payload: dict[str, Any], *, correlation_id: str, session: boto3.Session | None = None
) -> dict[str, Any]:
    analyzer_arn = str(payload["analyzer_arn"])
    max_findings = int(payload.get("max_findings", 500))
    boto_session = session or cross_account.assume(
        analyzer_arn.split(":")[4], feature_id="F2", correlation_id=correlation_id
    )
    result = scan_and_classify(analyzer_arn, max_findings, session=boto_session)
    true_positives = [c for c in result.classifications if c.classification == "TRUE_POSITIVE"]
    verdict = "CONFIRM" if true_positives else "REJECT"
    reason = (
        f"{len(true_positives)} true-positive finding(s) of {len(result.classifications)} "
        f"classified ({result.total_findings} total active)"
    )
    return {
        "verdict": verdict,
        "reason": reason,
        "findings": [c.model_dump(mode="json") for c in result.classifications],
        "remediation": None,
    }


def data_event_fast(
    payload: dict[str, Any],
    *,
    correlation_id: str,
    athena_client: AthenaClient | None = None,
) -> dict[str, Any]:
    role_arn = str(payload["role_arn"])
    days_back = int(payload.get("days_back", 30))
    result = query_data_events(
        role_arn, days_back, correlation_id=correlation_id, athena_client=athena_client
    )
    usage = result["usage"]
    verdict = "CONFIRM" if usage else "REJECT"
    reason = f"{len(usage)} S3 data-event usage pattern(s) found for {role_arn} over {days_back}d"
    return {"verdict": verdict, "reason": reason, "findings": usage, "remediation": None}


def shadow_guard_fast(
    query: dict[str, Any], *, findings_client: FindingsClient | None = None
) -> dict[str, Any]:
    """The one `GET` fast-path route (`/monitor/shadow-violations`) --
    shaped to match `FastPathTargetResponse`/`ShadowViolationsPage`
    (`items`, `next_token`), not `FastPathResponse` (verdict/findings),
    per `RouterBridgeService.dispatch_read`'s own docstring.
    """
    days_back = int(query.get("days_back", 7))
    severity_filter = cast("Severity", query.get("severity_filter", "MEDIUM"))
    violations, total_events_ingested = load_recent_violations(
        days_back=days_back, findings=findings_client
    )
    payload, controls = build_report(
        violations,
        days_back=days_back,
        severity_filter=severity_filter,
        total_events_ingested=total_events_ingested,
    )
    return {
        "items": [v.model_dump(mode="json") for v in payload.violations],
        "next_token": None,
        "compensating_controls": [c.model_dump(mode="json") for c in controls],
    }
