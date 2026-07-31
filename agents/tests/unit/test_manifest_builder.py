"""Sentence tokenizer determinism and span/hash stability (agents phase-10
§7 test plan)."""

from __future__ import annotations

from iam_sentinel_agents.contracts.quote_hash import canonical_quote_hash
from iam_sentinel_agents.knowledge_base.manifest_builder import (
    canonical_manifest_digest,
    generate_spans,
    tokenize_sentences,
)

_TEXT = (
    "PassRole is not an API call. No CloudTrail logs are generated for "
    "iam:PassRole. It is not tracked."
)


def test_tokenize_sentences_splits_on_boundaries() -> None:
    sentences = tokenize_sentences(_TEXT)

    assert sentences == [
        "PassRole is not an API call.",
        "No CloudTrail logs are generated for iam:PassRole.",
        "It is not tracked.",
    ]


def test_generate_spans_produces_1_2_and_3_sentence_windows() -> None:
    spans = generate_spans(_TEXT, corpus="iam", document="passrole.md", retrieved_on="2026-07-30")

    # 3 sentences -> 3 one-sentence + 2 two-sentence + 1 three-sentence = 6.
    assert len(spans) == 6
    assert all(span.span_end > span.span_start for span in spans)
    three_sentence_span = next(
        s for s in spans if s.span_end - s.span_start == len(_TEXT.encode("utf-8"))
    )
    assert three_sentence_span.quote_sha256 == canonical_quote_hash(_TEXT)


def test_canonical_manifest_digest_is_deterministic() -> None:
    spans = generate_spans(_TEXT, corpus="iam", document="passrole.md", retrieved_on="2026-07-30")

    hex_a, digest_a = canonical_manifest_digest(spans)
    hex_b, digest_b = canonical_manifest_digest(spans)

    assert hex_a == hex_b
    assert digest_a == digest_b
