"""Pydantic v2 contracts shared across every producer/consumer boundary.

Canonical source: /docs/DATA_CONTRACTS.md.
"""

from iam_sentinel_agents.contracts.common import (
    ACCOUNT_ID_PATTERN,
    ARN_PATTERN,
    Base,
    FeatureID,
    Severity,
    ULID_PATTERN,
    Verdict,
)
from iam_sentinel_agents.contracts.data_event import (
    DataEventPolicyPayload,
    S3DataEventAction,
    S3DataEventUsage,
)
from iam_sentinel_agents.contracts.decision import DecisionRecord
from iam_sentinel_agents.contracts.evidence import EvidenceKind, EvidenceRecord, EvidenceRef
from iam_sentinel_agents.contracts.finding import AwsDocCitation, Finding
from iam_sentinel_agents.contracts.knowledge_base import Corpus, KbManifest, QuoteHash
from iam_sentinel_agents.contracts.memory import (
    EpisodicMemory,
    MemoryKind,
    ProceduralHit,
    RecallResult,
    SemanticEntity,
    SemanticEntityKind,
)
from iam_sentinel_agents.contracts.org_context import (
    FALSE_POSITIVE_CLASSIFICATIONS,
    MatchedConditionKey,
    ORG_ID_PATTERN,
    OrgContextClassification,
    OrgContextClassificationKind,
    OrgContextPayload,
)
from iam_sentinel_agents.contracts.passrole import (
    BlastPath,
    PassRoleBlastPayload,
    PassRoleEdge,
    ReachedPrivilege,
)
from iam_sentinel_agents.contracts.query import SentinelQuery
from iam_sentinel_agents.contracts.remediation import (
    RemediationAction,
    RemediationPlan,
    ZelkovaCheck,
)
from iam_sentinel_agents.contracts.shadow_guard import (
    CompensatingControl,
    ShadowViolation,
    ShadowViolationPayload,
)
from iam_sentinel_agents.contracts.task import SpecialistTask, UntrustedContextBlock
from iam_sentinel_agents.contracts.verdict import SpecialistVerdict, ToolInvocation

__all__ = [
    "ACCOUNT_ID_PATTERN",
    "ARN_PATTERN",
    "FALSE_POSITIVE_CLASSIFICATIONS",
    "ORG_ID_PATTERN",
    "ULID_PATTERN",
    "AwsDocCitation",
    "Base",
    "BlastPath",
    "CompensatingControl",
    "Corpus",
    "DataEventPolicyPayload",
    "DecisionRecord",
    "EpisodicMemory",
    "EvidenceKind",
    "EvidenceRecord",
    "EvidenceRef",
    "FeatureID",
    "Finding",
    "KbManifest",
    "MatchedConditionKey",
    "MemoryKind",
    "OrgContextClassification",
    "OrgContextClassificationKind",
    "OrgContextPayload",
    "PassRoleBlastPayload",
    "PassRoleEdge",
    "ProceduralHit",
    "QuoteHash",
    "ReachedPrivilege",
    "RecallResult",
    "RemediationAction",
    "RemediationPlan",
    "S3DataEventAction",
    "S3DataEventUsage",
    "SemanticEntity",
    "SemanticEntityKind",
    "SentinelQuery",
    "Severity",
    "ShadowViolation",
    "ShadowViolationPayload",
    "SpecialistTask",
    "SpecialistVerdict",
    "ToolInvocation",
    "UntrustedContextBlock",
    "Verdict",
    "ZelkovaCheck",
]
