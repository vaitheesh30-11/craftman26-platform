from __future__ import annotations

from datetime import UTC, datetime

from iam_sentinel_adapters.evidence.keys import derive_evidence_key


def test_key_format_matches_spec() -> None:
    when = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)

    key = derive_evidence_key(
        feature_id="F1",
        correlation_id="corr-123",
        kind="specialist_output",
        body_sha256="abc123",
        when=when,
    )

    assert key == "F1/2026/07/30/corr-123/specialist_output/abc123.json"


def test_key_is_idempotent_for_identical_body_hash() -> None:
    when = datetime(2026, 7, 30, tzinfo=UTC)
    first = derive_evidence_key(
        feature_id="F2", correlation_id="c", kind="fault", body_sha256="same-hash", when=when
    )
    second = derive_evidence_key(
        feature_id="F2", correlation_id="c", kind="fault", body_sha256="same-hash", when=when
    )
    assert first == second
