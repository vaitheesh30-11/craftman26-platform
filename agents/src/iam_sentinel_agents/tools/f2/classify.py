"""org_context_scan -- phase-03 §4 Steps 2, 3, 5, 6: fetch active Access
Analyzer findings, classify each against real AWS Organizations data, and
return an `OrgContextPayload`.

`AccessStillGrantedCheck` (Step 3's "Otherwise, call
CheckAccessNotGranted...") is an injection point rather than a concrete
`accessanalyzer:CheckAccessNotGranted` call -- see docs/decisions/0023 §2
for why: that API needs the *original resource policy* the finding was
generated from (S3 bucket policy, IAM role trust policy, KMS key policy,
...), which `GetFinding` does not return verbatim, and no moto backend
exists for Access Analyzer to verify a resource-policy-refetch-and-strip
implementation against (ADR 0008's precedent). The default check fails
closed to `True` ("still grants access" -> TRUE_POSITIVE) -- the one
outcome the spec's own acceptance criteria and SAFETY clause both treat as
safe to be wrong about defensively (never archived, never suppressed).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TYPE_CHECKING

from botocore.config import Config

from iam_sentinel_agents.contracts.org_context import OrgContextClassification, OrgContextPayload
from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f2 import condition as cond
from iam_sentinel_agents.tools.f2.org_tree import fetch_org_context, OrgContext, OrgContextCache

if TYPE_CHECKING:
    import boto3
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_accessanalyzer.client import AccessAnalyzerClient

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

# phase-03 §5: "Access Analyzer TPS is low... enforce a max concurrent of 4
# in-flight GetFinding calls per invocation."
_MAX_CONCURRENT_GET_FINDING = 4
_DEFAULT_MAX_FINDINGS = 500
# Hard ceiling on how many active finding ids we'll enumerate to compute an
# accurate `total_findings` even when `max_findings` caps classification --
# unbounded pagination against a misconfigured analyzer would never return.
_HARD_LIST_CEILING = 5_000

AccessStillGrantedCheck = Callable[[dict[str, Any]], bool]


def _default_access_still_granted(_finding: dict[str, Any]) -> bool:
    return True


def _access_analyzer_client(session: boto3.Session) -> AccessAnalyzerClient:
    return session.client(
        "accessanalyzer",
        config=Config(retries={"max_attempts": 10, "mode": "adaptive"}),
    )


def _list_active_finding_ids(
    client: AccessAnalyzerClient, analyzer_arn: str, *, hard_ceiling: int = _HARD_LIST_CEILING
) -> list[str]:
    ids: list[str] = []
    paginator = client.get_paginator("list_findings")
    for page in paginator.paginate(analyzerArn=analyzer_arn, filter={"status": {"eq": ["ACTIVE"]}}):
        for finding in page["findings"]:
            ids.append(finding["id"])
            if len(ids) >= hard_ceiling:
                return ids
    return ids


def _get_findings_bounded(
    client: AccessAnalyzerClient, analyzer_arn: str, finding_ids: list[str]
) -> list[dict[str, Any]]:
    def _fetch(finding_id: str) -> dict[str, Any]:
        return dict(client.get_finding(analyzerArn=analyzer_arn, id=finding_id)["finding"])

    if not finding_ids:
        return []
    with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_GET_FINDING) as pool:
        return list(pool.map(_fetch, finding_ids))


def classify_finding(
    finding: dict[str, Any],
    *,
    analyzer_arn: str,
    org: OrgContext,
    access_still_granted: AccessStillGrantedCheck,
) -> OrgContextClassification:
    finding_condition: dict[str, str] = dict(finding.get("condition") or {})
    finding_id = str(finding["id"])

    org_id_value = cond.org_id_matches(finding_condition, org.org_id)
    if org_id_value is not None:
        return OrgContextClassification(
            finding_id=finding_id,
            analyzer_arn=analyzer_arn,
            classification="FALSE_POSITIVE_ORG_SCOPED",
            org_id=org.org_id,
            matched_condition_key="aws:PrincipalOrgId",
            matched_condition_value=org_id_value,
            real_ou_paths=org.ou_paths,
            real_account_ids=org.account_ids,
            rationale=f"condition aws:PrincipalOrgId={org_id_value!r} matches real org {org.org_id}",
        )

    account_value = cond.account_matches(finding_condition, org.account_ids)
    if account_value is not None:
        return OrgContextClassification(
            finding_id=finding_id,
            analyzer_arn=analyzer_arn,
            classification="FALSE_POSITIVE_ACCOUNT_SCOPED",
            org_id=org.org_id,
            matched_condition_key="aws:PrincipalAccount",
            matched_condition_value=account_value,
            real_ou_paths=org.ou_paths,
            real_account_ids=org.account_ids,
            rationale=f"condition aws:PrincipalAccount={account_value!r} matches a real member account",
        )

    ou_path_value = cond.org_paths_match(finding_condition, org.ou_paths)
    if ou_path_value is not None:
        return OrgContextClassification(
            finding_id=finding_id,
            analyzer_arn=analyzer_arn,
            classification="FALSE_POSITIVE_ORG_SCOPED",
            org_id=org.org_id,
            matched_condition_key="aws:PrincipalOrgPaths",
            matched_condition_value=ou_path_value,
            real_ou_paths=org.ou_paths,
            real_account_ids=org.account_ids,
            rationale=f"condition aws:PrincipalOrgPaths={ou_path_value!r} matches a real OU path",
        )

    still_granted = access_still_granted(finding)
    classification = "TRUE_POSITIVE" if still_granted else "INCONCLUSIVE_UNKNOWN_CONDITION"
    return OrgContextClassification(
        finding_id=finding_id,
        analyzer_arn=analyzer_arn,
        classification=classification,
        org_id=org.org_id,
        matched_condition_key=None,
        matched_condition_value="",
        real_ou_paths=org.ou_paths,
        real_account_ids=org.account_ids,
        rationale=(
            "no aws:PrincipalOrgId/PrincipalAccount/PrincipalOrgPaths condition matched; "
            f"access-not-granted check reports access is "
            f"{'still granted' if still_granted else 'not granted'}"
        ),
    )


def scan_and_classify(
    analyzer_arn: str,
    max_findings: int = _DEFAULT_MAX_FINDINGS,
    *,
    session: boto3.Session,
    cache: OrgContextCache | None = None,
    access_still_granted: AccessStillGrantedCheck = _default_access_still_granted,
) -> OrgContextPayload:
    bounded_max = max(1, min(max_findings, _HARD_LIST_CEILING))
    client = _access_analyzer_client(session)
    org = fetch_org_context(session, cache=cache)

    all_finding_ids = _list_active_finding_ids(client, analyzer_arn)
    classify_ids = all_finding_ids[:bounded_max]
    findings = _get_findings_bounded(client, analyzer_arn, classify_ids)

    classifications = [
        classify_finding(
            finding, analyzer_arn=analyzer_arn, org=org, access_still_granted=access_still_granted
        )
        for finding in findings
    ]

    return OrgContextPayload(
        analyzer_arn=analyzer_arn,
        total_findings=len(all_finding_ids),
        classifications=classifications,
        archived_count=0,
        archive_rule_id=None,
    )


@sentinel_handler(feature_id="F2", tool_name="org_context_scan")
def org_context_scan(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    analyzer_arn = invocation.parameters["analyzer_arn"]
    max_findings = int(invocation.parameters.get("max_findings", _DEFAULT_MAX_FINDINGS))
    account_id = analyzer_arn.split(":")[4]
    session = cross_account.assume(
        account_id, feature_id="F2", correlation_id=invocation.correlation_id
    )
    payload = scan_and_classify(analyzer_arn, max_findings, session=session)
    return payload.model_dump(mode="json")


# Retained for callers that need wall-clock instrumentation without going
# through the full Bedrock envelope (e.g. a future weekly-report Lambda).
def scan_and_classify_timed(
    analyzer_arn: str, max_findings: int, *, session: boto3.Session
) -> tuple[OrgContextPayload, int]:
    start = time.monotonic()
    payload = scan_and_classify(analyzer_arn, max_findings, session=session)
    return payload, int((time.monotonic() - start) * 1000)
