"""Content-addressed evidence key derivation (phase-04 §5).

`feature_id` prefix eases IAM scoping, date partitioning eases lifecycle
rules, and the `body_sha256` suffix prevents duplicate writes and makes
`put_signed_evidence` idempotent for identical bodies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

FeatureID = Literal["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
EvidenceKind = Literal[
    "specialist_input",
    "specialist_output",
    "zelkova_invocation",
    "policy_mutation",
    "guardrail_intervention",
    "repair_action",
    "fault",
]


def derive_evidence_key(
    *,
    feature_id: FeatureID,
    correlation_id: str,
    kind: EvidenceKind,
    body_sha256: str,
    when: datetime,
) -> str:
    return f"{feature_id}/{when:%Y}/{when:%m}/{when:%d}/{correlation_id}/{kind}/{body_sha256}.json"
