"""OrgContextPayload -- F2 Org Context Validator's feature payload.

Canonical source: agents/docs/phase-03-org-context-validator.txt §3. Pure
data contract, same shape as `contracts/passrole.py`: the Bedrock Agent
itself assembles `Finding.payload` from `org_context_scan`'s JSON response
per the specialist prompt's REASONING CONTRACT; `tools/f2/classify.py`
constructs `OrgContextPayload` so tests can assert on one concrete object.

Deviation from phase-03 §3's literal Pydantic snippet -- see
docs/decisions/0023: `matched_condition_key`/`matched_condition_value` are
made optional here. The spec's own Step 3 algorithm has a branch ("Otherwise,
call CheckAccessNotGranted...") that produces TRUE_POSITIVE or
INCONCLUSIVE_UNKNOWN_CONDITION classifications precisely when *none* of the
three condition keys matched -- a required, three-value Literal field
cannot represent "no condition key matched" without inventing a value never
present in any real finding, which the REASONING CONTRACT's "never invent"
rule forbids just as much for a specialist as for a payload field.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from iam_sentinel_agents.contracts.common import ACCOUNT_ID_PATTERN, ARN_PATTERN, Base

ORG_ID_PATTERN = r"^o-[a-z0-9]{10,32}$"

OrgContextClassificationKind = Literal[
    "TRUE_POSITIVE",
    "FALSE_POSITIVE_ORG_SCOPED",
    "FALSE_POSITIVE_ACCOUNT_SCOPED",
    "INCONCLUSIVE_UNKNOWN_CONDITION",
]

MatchedConditionKey = Literal[
    "aws:PrincipalOrgId",
    "aws:PrincipalAccount",
    "aws:PrincipalOrgPaths",
]

_AccountId = Annotated[str, Field(pattern=ACCOUNT_ID_PATTERN)]

FALSE_POSITIVE_CLASSIFICATIONS: frozenset[OrgContextClassificationKind] = frozenset(
    {"FALSE_POSITIVE_ORG_SCOPED", "FALSE_POSITIVE_ACCOUNT_SCOPED"}
)


class OrgContextClassification(Base):
    finding_id: str = Field(min_length=1, max_length=2048)
    analyzer_arn: str = Field(pattern=ARN_PATTERN)
    classification: OrgContextClassificationKind
    org_id: str = Field(pattern=ORG_ID_PATTERN)
    matched_condition_key: MatchedConditionKey | None = None
    matched_condition_value: str = Field(default="", max_length=2048)
    real_ou_paths: list[str] = Field(default_factory=list, max_length=10_000)
    real_account_ids: list[_AccountId] = Field(default_factory=list, max_length=10_000)
    rationale: str = Field(min_length=1, max_length=2048)


class OrgContextPayload(Base):
    analyzer_arn: str = Field(pattern=ARN_PATTERN)
    total_findings: int = Field(ge=0)
    classifications: list[OrgContextClassification] = Field(default_factory=list, max_length=500)
    archived_count: int = Field(ge=0)
    archive_rule_id: str | None = None
