"""Pydantic v2 contracts shared across every producer/consumer boundary.

Canonical source: /docs/DATA_CONTRACTS.md.
"""

from iam_sentinel_agents.contracts.common import (
    Base,
    FeatureID,
    Severity,
    Verdict,
    ULID_PATTERN,
    ACCOUNT_ID_PATTERN,
    ARN_PATTERN,
)
from iam_sentinel_agents.contracts.decision import DecisionRecord
from iam_sentinel_agents.contracts.evidence import EvidenceKind, EvidenceRecord, EvidenceRef
from iam_sentinel_agents.contracts.finding import AwsDocCitation, Finding
from iam_sentinel_agents.contracts.query import SentinelQuery
from iam_sentinel_agents.contracts.remediation import RemediationAction, RemediationPlan, ZelkovaCheck
from iam_sentinel_agents.contracts.task import SpecialistTask, UntrustedContextBlock
from iam_sentinel_agents.contracts.verdict import SpecialistVerdict, ToolInvocation

__all__ = [
    "ACCOUNT_ID_PATTERN",
    "ARN_PATTERN",
    "AwsDocCitation",
    "Base",
    "DecisionRecord",
    "EvidenceKind",
    "EvidenceRecord",
    "EvidenceRef",
    "FeatureID",
    "Finding",
    "RemediationAction",
    "RemediationPlan",
    "SentinelQuery",
    "Severity",
    "SpecialistTask",
    "SpecialistVerdict",
    "ToolInvocation",
    "ULID_PATTERN",
    "UntrustedContextBlock",
    "Verdict",
    "ZelkovaCheck",
]
