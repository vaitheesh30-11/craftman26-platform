"""DataEventPolicyPayload — F3 Data Event Enricher's feature payload.

Canonical source: agents/docs/phase-04-data-event-enricher.txt §3. Same
shape of "pure data contract" note as F1's `PassRoleBlastPayload`
(contracts/passrole.py): the Bedrock Agent itself assembles
`Finding.payload` from the three tools' JSON responses plus the
`base_policy_generate`/Zelkova-precheck runtime helper
(tools/f3/policy_generation.py) per the specialist prompt's REASONING
CONTRACT — `policy_generation.build_data_event_payload` exists so tests can
exercise the whole pipeline against one concrete object.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from iam_sentinel_agents.contracts.common import ARN_PATTERN, Base
from iam_sentinel_agents.contracts.remediation import ZelkovaCheck

S3DataEventAction = Literal[
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:ListMultipartUploadParts",
    "s3:AbortMultipartUpload",
]


class S3DataEventUsage(Base):
    action: S3DataEventAction
    bucket: str = Field(min_length=3, max_length=255)
    prefixes: list[str] = Field(default_factory=list, max_length=10_000)
    consolidated_prefix: str | None = Field(default=None, max_length=2048)
    call_count: int = Field(ge=0)


class DataEventPolicyPayload(Base):
    role_arn: str = Field(pattern=ARN_PATTERN)
    days_back: int = Field(ge=1, le=90)
    base_policy: dict[str, object]
    data_event_usage: list[S3DataEventUsage] = Field(default_factory=list, max_length=1_000)
    merged_policy: dict[str, object]
    merged_policy_bytes: int = Field(ge=0)
    truncated: bool
    zelkova_pre: ZelkovaCheck
