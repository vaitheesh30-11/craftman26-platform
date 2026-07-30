"""KB quote-manifest contracts (agents phase-10 §3).

`QuoteHash` is one hashed 1-3 sentence span of a corpus document;
`KbManifest` is the KMS-signed index of all of them that
`Finding.aws_doc_citation.quote`'s validator checks against (see
`contracts/finding.py` and `knowledge_base/manifest_provider.py`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator, NonNegativeInt

from iam_sentinel_agents.contracts.common import Base, ISO_DATE_PATTERN, SHA256_PATTERN

Corpus = Literal["iam", "organizations", "identity_center", "service_auth_ref"]


class QuoteHash(Base):
    quote_sha256: str = Field(pattern=SHA256_PATTERN)
    corpus: Corpus
    document: str = Field(min_length=1, max_length=1024)
    span_start: NonNegativeInt
    span_end: NonNegativeInt
    retrieved_on: str = Field(pattern=ISO_DATE_PATTERN)

    @model_validator(mode="after")
    def _span_end_after_start(self) -> QuoteHash:
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be greater than span_start")
        return self


class KbManifest(Base):
    manifest_version: str = Field(min_length=1, max_length=32)
    generated_at: AwareDatetime
    total_quotes: NonNegativeInt
    quotes: list[QuoteHash]
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    signature: str = Field(min_length=1, max_length=4096)
    kms_key_arn: str = Field(min_length=20, max_length=2048)

    @model_validator(mode="after")
    def _total_quotes_matches_list(self) -> KbManifest:
        if self.total_quotes != len(self.quotes):
            raise ValueError("total_quotes must equal len(quotes)")
        return self
