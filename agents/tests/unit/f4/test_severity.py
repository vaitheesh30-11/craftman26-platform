from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f4.severity import assign_severity

pytestmark = pytest.mark.unit


def test_high_volume_production_account_is_critical() -> None:
    assert assign_severity(1500, is_production_account=True) == "CRITICAL"


def test_high_volume_without_a_confirmed_production_tag_falls_back_to_high() -> None:
    # phase-05's own Risk section: missing production tag data degrades the
    # rubric to call-count-only rather than raising CRITICAL speculatively.
    assert assign_severity(1500, is_production_account=None) == "HIGH"


def test_moderate_volume_is_high() -> None:
    assert assign_severity(150) == "HIGH"


def test_low_volume_is_medium() -> None:
    assert assign_severity(5) == "MEDIUM"
