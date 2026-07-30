"""KMS-signed, canonicalized evidence primitives (phase-04)."""

from __future__ import annotations

from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json
from iam_sentinel_adapters.evidence.client import EvidenceClient, EvidenceRef
from iam_sentinel_adapters.evidence.keys import EvidenceKind, FeatureID, derive_evidence_key

__all__ = [
    "EvidenceClient",
    "EvidenceKind",
    "EvidenceRef",
    "FeatureID",
    "canonicalize_json",
    "derive_evidence_key",
]
