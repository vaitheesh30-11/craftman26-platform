"""org_context_suppress -- phase-03 §4 Step 4: archive confirmed
false-positive findings in batches of 25 and create/update an idempotent
archive rule.

`select_archivable_finding_ids` is the acceptance-criterion guard ("Never
archives a TRUE_POSITIVE" -- §9): it is the only place that decides which
`OrgContextClassification`s are eligible to be archived, so a property test
can assert the invariant directly against arbitrary classification mixes
without needing a live Access Analyzer call. The Lambda handler itself
trusts its caller's `finding_ids` (the specialist prompt's WORKFLOW step 3
already restricts calls to `FALSE_POSITIVE_ORG_SCOPED` ids) -- this module
does not re-derive classifications from `finding_ids` alone because the tool
contract (phase-03 §3) never gives it the classification, only the id.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from iam_sentinel_agents.contracts.org_context import (
    FALSE_POSITIVE_CLASSIFICATIONS,
    OrgContextClassification,
)
from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f2.org_tree import fetch_org_context

if TYPE_CHECKING:
    import boto3
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_accessanalyzer.client import AccessAnalyzerClient

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

_BATCH_SIZE = 25
_RULE_NAME_TEMPLATE = "sentinel-org-scoped-suppression-{org_id}"


def select_archivable_finding_ids(classifications: list[OrgContextClassification]) -> list[str]:
    """Only FALSE_POSITIVE_* classifications may ever be archived."""
    return [
        c.finding_id for c in classifications if c.classification in FALSE_POSITIVE_CLASSIFICATIONS
    ]


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _analyzer_name_from_arn(analyzer_arn: str) -> str:
    """Archive-rule operations (Get/Create/UpdateArchiveRule) key on the
    analyzer's *name*, not its ARN, unlike ListFindings/GetFinding/
    UpdateFindings which take `analyzerArn` -- a real, easy-to-miss AWS API
    asymmetry (see `mypy_boto3_accessanalyzer.type_defs`:
    `GetArchiveRuleRequestRequestTypeDef.analyzerName` vs.
    `GetFindingRequestRequestTypeDef.analyzerArn`) caught by `mypy --strict`
    against the real boto3 stubs, not by any AWS documentation quote.
    """
    return analyzer_arn.rsplit("/", 1)[-1]


def _upsert_archive_rule(client: AccessAnalyzerClient, *, analyzer_arn: str, org_id: str) -> str:
    rule_name = _RULE_NAME_TEMPLATE.format(org_id=org_id)
    analyzer_name = _analyzer_name_from_arn(analyzer_arn)
    filter_: dict[str, Any] = {"condition.aws:PrincipalOrgId": {"eq": [org_id]}}
    try:
        client.get_archive_rule(analyzerName=analyzer_name, ruleName=rule_name)
    except client.exceptions.ResourceNotFoundException:
        client.create_archive_rule(analyzerName=analyzer_name, ruleName=rule_name, filter=filter_)
    else:
        client.update_archive_rule(analyzerName=analyzer_name, ruleName=rule_name, filter=filter_)
    return rule_name


def suppress_findings(
    finding_ids: list[str],
    analyzer_arn: str,
    *,
    org_id: str,
    session: boto3.Session,
    create_rule: bool = True,
) -> dict[str, Any]:
    client: AccessAnalyzerClient = session.client("accessanalyzer")

    archived = 0
    for batch in _chunks(finding_ids, _BATCH_SIZE):
        if not batch:
            continue
        client.update_findings(analyzerArn=analyzer_arn, ids=batch, status="ARCHIVED")
        archived += len(batch)

    rule_id: str | None = None
    if create_rule and finding_ids:
        rule_id = _upsert_archive_rule(client, analyzer_arn=analyzer_arn, org_id=org_id)

    return {"archived": archived, "rule_id": rule_id}


@sentinel_handler(feature_id="F2", tool_name="org_context_suppress")
def org_context_suppress(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    """Per the action group's OpenAPI schema (§6), `org_id` is not a caller
    parameter -- it is derived from the same cached org-context fetch
    `org_context_scan` uses, so a caller can never smuggle in a mismatched
    `org_id` for the archive-rule filter.
    """
    analyzer_arn = invocation.parameters["analyzer_arn"]
    finding_ids = list(invocation.parameters["finding_ids"])
    create_rule = bool(invocation.parameters.get("create_rule", True))
    account_id = analyzer_arn.split(":")[4]

    session = cross_account.assume(
        account_id, feature_id="F2", correlation_id=invocation.correlation_id
    )
    org_id = fetch_org_context(session).org_id
    return suppress_findings(
        finding_ids, analyzer_arn, org_id=org_id, session=session, create_rule=create_rule
    )
