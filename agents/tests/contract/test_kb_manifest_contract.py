"""KbManifest/QuoteHash internal-consistency checks (agents phase-10 §3)."""

from __future__ import annotations

from datetime import datetime, UTC

import pytest
from pydantic import ValidationError

from iam_sentinel_agents.contracts import KbManifest, QuoteHash

pytestmark = pytest.mark.contract

_VALID_QUOTE = {
    "quote_sha256": "a" * 64,
    "corpus": "iam",
    "document": "passrole.md",
    "span_start": 0,
    "span_end": 42,
    "retrieved_on": "2026-07-30",
}


def test_quote_hash_rejects_span_end_before_start() -> None:
    with pytest.raises(ValidationError, match="span_end must be greater"):
        QuoteHash(**{**_VALID_QUOTE, "span_start": 42, "span_end": 0})


def test_kb_manifest_rejects_total_quotes_mismatch() -> None:
    with pytest.raises(ValidationError, match="total_quotes must equal"):
        KbManifest(
            manifest_version="1",
            generated_at=datetime.now(UTC),
            total_quotes=2,
            quotes=[QuoteHash(**_VALID_QUOTE)],
            manifest_sha256="b" * 64,
            signature="c2lnbmF0dXJl",
            kms_key_arn="arn:aws:kms:us-east-1:111111111111:key/kb-manifest",
        )


def test_kb_manifest_round_trip() -> None:
    manifest = KbManifest(
        manifest_version="1",
        generated_at=datetime.now(UTC),
        total_quotes=1,
        quotes=[QuoteHash(**_VALID_QUOTE)],
        manifest_sha256="b" * 64,
        signature="c2lnbmF0dXJl",
        kms_key_arn="arn:aws:kms:us-east-1:111111111111:key/kb-manifest",
    )

    assert KbManifest.model_validate(manifest.model_dump(mode="json")) == manifest
