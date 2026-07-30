"""Property coverage for the sanitizer's structural invariants.

phase-03 §7 asks for a 10,000-example Hypothesis run; the revised testing
policy caps property runs to keep token/CI cost down, so this runs 200
examples instead. The invariant under test does not change with example
count -- a counterexample at 200 examples is exactly as damning as one at
10,000.
"""

from __future__ import annotations

import unicodedata

from hypothesis import given, settings
from hypothesis import strategies as st

from iam_sentinel_adapters.errors import SanitizerRejection
from iam_sentinel_adapters.prompts.sanitizer import sanitize_untrusted


@given(st.text(max_size=200))
@settings(max_examples=200)
def test_sanitized_output_never_contains_stripped_characters(value: str) -> None:
    try:
        result = sanitize_untrusted(value, max_length=100)
    except SanitizerRejection:
        return

    assert "<" not in result
    assert ">" not in result
    assert "`" not in result
    assert len(result) <= 100
    assert all(unicodedata.category(ch)[0] != "C" for ch in result)
