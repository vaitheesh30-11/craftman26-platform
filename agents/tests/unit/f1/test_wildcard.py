"""ARN wildcard resolver correctness (phase-02 §8 property test + §9
acceptance: "wildcard resolver correctness verified on all four fixtures").
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from iam_sentinel_agents.tools.f1.wildcard import resolve_role_pattern

pytestmark = pytest.mark.unit


def test_concrete_arn_matches_only_itself() -> None:
    candidates = [
        "arn:aws:iam::123456789012:role/AdminRole",
        "arn:aws:iam::123456789012:role/OtherRole",
    ]
    assert resolve_role_pattern("arn:aws:iam::123456789012:role/AdminRole", candidates) == [
        "arn:aws:iam::123456789012:role/AdminRole"
    ]


def test_wildcard_in_account_segment() -> None:
    candidates = [
        "arn:aws:iam::123456789012:role/prod-web",
        "arn:aws:iam::999999999999:role/prod-api",
    ]
    assert resolve_role_pattern("arn:aws:iam::*:role/prod-*", candidates) == candidates


def test_wildcard_excludes_non_matching_role_names() -> None:
    candidates = [
        "arn:aws:iam::123456789012:role/prod-web",
        "arn:aws:iam::123456789012:role/staging-web",
    ]
    resolved = resolve_role_pattern("arn:aws:iam::123456789012:role/prod-*", candidates)
    assert resolved == ["arn:aws:iam::123456789012:role/prod-web"]


def test_no_match_returns_empty_list() -> None:
    assert (
        resolve_role_pattern(
            "arn:aws:iam::123456789012:role/nope-*", ["arn:aws:iam::123456789012:role/x"]
        )
        == []
    )


@given(
    role_name=st.text(alphabet=st.characters(blacklist_characters="*?[]"), min_size=1, max_size=20)
)
@settings(max_examples=200)
def test_concrete_pattern_never_matches_a_different_role_name(role_name: str) -> None:
    pattern = f"arn:aws:iam::123456789012:role/{role_name}"
    other = f"arn:aws:iam::123456789012:role/{role_name}-suffix"
    assert resolve_role_pattern(pattern, [other]) == []
    assert resolve_role_pattern(pattern, [pattern]) == [pattern]
