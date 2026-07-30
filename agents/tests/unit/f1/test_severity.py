"""Blast-score rollup across a principal's `BlastPath`s (phase-02 §3.3)."""

from __future__ import annotations

import pytest

from iam_sentinel_agents.contracts.passrole import BlastPath
from iam_sentinel_agents.tools.f1.severity import blast_score

pytestmark = pytest.mark.unit


def _path(reached_privilege: str, hop_count: int = 1) -> BlastPath:
    return BlastPath(
        hops=["arn:aws:iam::123456789012:user/A", "arn:aws:iam::123456789012:role/B"],
        reached_privilege=reached_privilege,
        hop_count=hop_count,
    )


def test_empty_paths_is_low() -> None:
    assert blast_score([]) == "LOW"


def test_administrator_access_is_critical() -> None:
    assert blast_score([_path("Other"), _path("AdministratorAccess")]) == "CRITICAL"


def test_power_user_and_iam_write_are_high() -> None:
    assert blast_score([_path("PowerUserAccess")]) == "HIGH"
    assert blast_score([_path("IAMWrite")]) == "HIGH"


def test_sensitive_service_is_medium() -> None:
    assert blast_score([_path("SensitiveService"), _path("Other")]) == "MEDIUM"


def test_other_only_is_low() -> None:
    assert blast_score([_path("Other"), _path("Other")]) == "LOW"


def test_highest_severity_wins_regardless_of_order() -> None:
    assert blast_score([_path("Other"), _path("SensitiveService"), _path("IAMWrite")]) == "HIGH"
