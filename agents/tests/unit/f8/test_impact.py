"""Impact-classification rubric (phase-09 §4 Step 3)."""

from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f8.impact import classify_impact

pytestmark = pytest.mark.unit


def test_rubric_boundaries() -> None:
    # Core-action hit is CRITICAL regardless of how small the ratio is.
    assert classify_impact(intersection_count=1, required_count=100, core_hit=True) == "CRITICAL"
    # >= 30% ratio is CRITICAL even without a core-action hit.
    assert classify_impact(intersection_count=3, required_count=10, core_hit=False) == "CRITICAL"
    # 10-30% is HIGH.
    assert classify_impact(intersection_count=2, required_count=10, core_hit=False) == "HIGH"
    # < 10% is MEDIUM.
    assert classify_impact(intersection_count=1, required_count=20, core_hit=False) == "MEDIUM"
