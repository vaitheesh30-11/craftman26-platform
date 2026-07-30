"""Canonical AWS-doc-quote hashing, shared by the `Finding` citation
validator and the KB manifest generator (agents phase-10 §3-4).

NFKC-normalize then collapse whitespace before hashing so that a quote
re-flowed across line breaks, or copied with a different Unicode
representation of the same character, still matches the manifest.
"""

from __future__ import annotations

import hashlib
import unicodedata


def canonical_quote_hash(quote: str) -> str:
    normalized = unicodedata.normalize("NFKC", quote)
    collapsed = " ".join(normalized.split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()
