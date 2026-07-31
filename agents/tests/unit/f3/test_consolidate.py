"""Prefix consolidation — phase-04 §4 Step 4 rules 3 (fanout collapse) and
4 (bucket-wide collapse with warning).
"""

from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f3.consolidate import consolidate_prefix

pytestmark = pytest.mark.unit


def test_single_key_returns_the_exact_key_with_no_wildcard() -> None:
    prefix, bucket_wide = consolidate_prefix(["reports/2026/q1.csv"])
    assert prefix == "reports/2026/q1.csv"
    assert bucket_wide is False


def test_shared_directory_collapses_to_prefix_wildcard() -> None:
    keys = ["logs/2026/01/a.json", "logs/2026/02/b.json", "logs/2026/03/c.json"]
    prefix, bucket_wide = consolidate_prefix(keys)
    assert prefix == "logs/2026/*"
    assert bucket_wide is False


def test_root_level_fanout_over_twenty_collapses_to_star_with_warning() -> None:
    keys = [f"tenant-{i}/config.json" for i in range(25)]
    prefix, bucket_wide = consolidate_prefix(keys)
    assert prefix == "*"
    assert bucket_wide is True


def test_empty_key_list_returns_none_without_a_warning() -> None:
    prefix, bucket_wide = consolidate_prefix([])
    assert prefix is None
    assert bucket_wide is False
