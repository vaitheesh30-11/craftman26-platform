"""Pure quote-manifest construction (agents phase-10 §4 steps 1-2).

No AWS calls: sentence tokenization, 1-3 sentence span windowing, and
per-span hashing. The S3/KMS boundary lives in
`iam_sentinel_adapters.knowledge_base.manifest_client.KbManifestClient`
(agents/ calls into adapters/ for that; this module is called by
`manifest_service.build_and_publish_manifest`, not the other way round).

The spec's nltk fallback path is the only path implemented here: no nltk
dependency is vendored anywhere in this repo, so this regex tokenizer is not
a fallback but the sole implementation.
"""

from __future__ import annotations

import hashlib
import re

from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json

from iam_sentinel_agents.contracts.knowledge_base import Corpus, QuoteHash
from iam_sentinel_agents.contracts.quote_hash import canonical_quote_hash

# Splits after sentence-ending punctuation followed by whitespace and a
# capital letter/opening quote/paren -- good enough for AWS doc prose
# (short declarative sentences, few abbreviations) without a full NLP
# tokenizer.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
_WINDOW_SIZES = (1, 2, 3)


def tokenize_sentences(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    return [s.strip() for s in _SENTENCE_BOUNDARY.split(stripped) if s.strip()]


def generate_spans(
    text: str, *, corpus: Corpus, document: str, retrieved_on: str
) -> list[QuoteHash]:
    """1-, 2-, and 3-sentence sliding windows over `text`, each hashed and
    offset-tracked in UTF-8 byte positions (the interface contract's
    `span_start`/`span_end` are byte offsets, per §3).
    """
    sentences = tokenize_sentences(text)
    if not sentences:
        return []

    char_starts: list[int] = []
    search_from = 0
    for sentence in sentences:
        start = text.index(sentence, search_from)
        char_starts.append(start)
        search_from = start + len(sentence)

    spans: list[QuoteHash] = []
    for window in _WINDOW_SIZES:
        for i in range(len(sentences) - window + 1):
            span_text = " ".join(sentences[i : i + window])
            char_start = char_starts[i]
            char_end = char_starts[i + window - 1] + len(sentences[i + window - 1])
            spans.append(
                QuoteHash(
                    quote_sha256=canonical_quote_hash(span_text),
                    corpus=corpus,
                    document=document,
                    span_start=len(text[:char_start].encode("utf-8")),
                    span_end=len(text[:char_end].encode("utf-8")),
                    retrieved_on=retrieved_on,
                )
            )
    return spans


def canonical_manifest_digest(quotes: list[QuoteHash]) -> tuple[str, bytes]:
    """sha256 over the sorted quotes list (§4 step 2). Returns (hex, raw
    digest bytes) -- the hex is stored in `KbManifest.manifest_sha256`, the
    raw bytes are what `KbManifestClient.sign` passes to `kms:Sign`.
    """
    body = [q.model_dump(mode="json") for q in quotes]
    canonical_bytes = canonicalize_json(body).encode("utf-8")
    digest = hashlib.sha256(canonical_bytes).digest()
    return digest.hex(), digest
