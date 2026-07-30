"""Freshness contract: retrievals older than 30 days are flagged
(agents phase-10 §4 step 6, §7 test plan)."""

from __future__ import annotations

from datetime import date

from iam_sentinel_agents.knowledge_base.freshness import is_stale


def test_recent_retrieval_is_not_stale() -> None:
    assert is_stale("2026-07-01", as_of=date(2026, 7, 30)) is False


def test_retrieval_older_than_30_days_is_stale() -> None:
    assert is_stale("2026-05-28", as_of=date(2026, 7, 30)) is True
