"""Finding — universal schema for anything a specialist surfaces.

Every Finding carries an `aws_doc_citation` whose `quote_sha256` must exist in
the KB quote manifest at load time. Manifest access is pluggable; tests inject
a fixture manifest, production reads a KMS-signed JSON from S3 (see agents
phase-10).
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any, Protocol, TYPE_CHECKING

from pydantic import AwareDatetime, Field, field_validator, model_validator

from iam_sentinel_agents.contracts.common import (
    ACCOUNT_ID_PATTERN,
    ARN_PATTERN,
    Base,
    FeatureID,
    ISO_DATE_PATTERN,
    Severity,
    ULID_PATTERN,
)
from iam_sentinel_agents.contracts.evidence import EvidenceRef

if TYPE_CHECKING:
    # `_MANIFEST_PROVIDER`'s annotation and `set_quote_manifest_provider`'s
    # parameter are both deferred (PEP 563) and never eagerly resolved — this
    # is a bare module-level callable, not a Pydantic model field, so unlike
    # every `Any`/`FeatureID` usage inside the classes below, nothing needs
    # this import to be real at runtime.
    from collections.abc import Callable


class QuoteManifest(Protocol):
    def contains(self, quote_sha256: str) -> bool: ...


def _canonical_quote_hash(quote: str) -> str:
    normalized = unicodedata.normalize("NFKC", quote)
    collapsed = " ".join(normalized.split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def _no_manifest_configured() -> QuoteManifest | None:
    return None


_MANIFEST_PROVIDER: Callable[[], QuoteManifest | None] = _no_manifest_configured


def set_quote_manifest_provider(provider: Callable[[], QuoteManifest | None]) -> None:
    """Install the manifest lookup used by Finding validators.

    Called once at Lambda cold start by the runtime; called with a fixture
    provider inside tests.
    """
    global _MANIFEST_PROVIDER  # noqa: PLW0603 — deliberate module-level swap
    _MANIFEST_PROVIDER = provider


class AwsDocCitation(Base):
    gap_id: FeatureID
    quote: str = Field(min_length=1, max_length=1024)
    source: str = Field(min_length=1, max_length=256)
    url: str = Field(pattern=r"^https://docs\.aws\.amazon\.com/.+")
    retrieved_on: str = Field(pattern=ISO_DATE_PATTERN)

    @property
    def quote_sha256(self) -> str:
        return _canonical_quote_hash(self.quote)

    @field_validator("quote")
    @classmethod
    def _quote_must_be_in_manifest(cls, value: str) -> str:
        manifest = _MANIFEST_PROVIDER()
        if manifest is None:
            return value
        if not manifest.contains(_canonical_quote_hash(value)):
            raise ValueError(
                "aws_doc_citation.quote not found in KB manifest; "
                "specialist cannot invent citations"
            )
        return value


class Finding(Base):
    finding_id: str = Field(pattern=ULID_PATTERN)
    feature_id: FeatureID
    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    principal_arn: str | None = Field(default=None, pattern=ARN_PATTERN)
    resource_arn: str | None = Field(default=None, pattern=ARN_PATTERN)
    severity: Severity
    title: str = Field(min_length=1, max_length=256)
    detail: str = Field(min_length=1, max_length=8192)
    aws_doc_citation: AwsDocCitation
    payload: dict[str, Any] = Field(default_factory=dict)
    detected_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    evidence_ref: EvidenceRef | None = None

    @model_validator(mode="after")
    def _critical_implies_principal(self) -> Finding:
        if self.severity == "CRITICAL" and self.principal_arn is None:
            raise ValueError("severity=CRITICAL requires principal_arn to be set")
        return self
