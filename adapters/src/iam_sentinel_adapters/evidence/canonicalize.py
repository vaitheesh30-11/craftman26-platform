"""RFC 8785 JSON Canonicalization Scheme (JCS) — pragmatic subset.

Produces a deterministic, whitespace-free, key-sorted JSON representation
used both to fence `trusted_input` into a prompt (phase-03 §4) and to
canonicalize evidence payloads before KMS signing (phase-04). Covers the
JSON types this platform actually produces (str, int, bool, None, dict,
list, and integral float); RFC 8785's exact ECMAScript float-formatting
rules for non-integral floats are not implemented — revisit if evidence
payloads ever carry them.
"""

from __future__ import annotations

import json
from typing import Any


def canonicalize_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
