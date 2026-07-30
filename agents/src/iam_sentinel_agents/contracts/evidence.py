"""EvidenceRef / EvidenceRecord — KMS-signed, S3-Object-Lock-persisted proof."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field

from iam_sentinel_agents.contracts.common import SHA256_PATTERN, ULID_PATTERN, Base, FeatureID

EvidenceKind = Literal[
    "specialist_input",
    "specialist_output",
    "zelkova_invocation",
    "policy_mutation",
    "guardrail_intervention",
    "repair_action",
    "fault",
]


class EvidenceRef(Base):
    bucket: str = Field(min_length=3, max_length=63)
    key: str = Field(min_length=1, max_length=1024)
    version_id: str = Field(min_length=1, max_length=1024)
    kms_key_arn: str = Field(min_length=20, max_length=2048)
    signature: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=SHA256_PATTERN)
    stored_at: AwareDatetime


class EvidenceRecord(Base):
    ref: EvidenceRef
    kind: EvidenceKind
    correlation_id: str = Field(pattern=ULID_PATTERN)
    feature_id: FeatureID
    body: dict[str, Any]
