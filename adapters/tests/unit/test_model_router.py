from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_adapters.llm.model_router import pick_model
from iam_sentinel_adapters.settings import settings


def _cost_meter(projected: float) -> MagicMock:
    meter = MagicMock()
    meter.projected.return_value = projected
    return meter


@pytest.mark.parametrize(
    ("projected", "request_hint", "expected"),
    [
        (0.0, None, settings.model_haiku_id),
        (0.0, "sonnet", settings.model_sonnet_id),
        (0.50, "sonnet", settings.model_sonnet_id),
        (0.69, "sonnet", settings.model_sonnet_id),
        (0.71, "sonnet", settings.model_haiku_id),
        (1.50, "sonnet", settings.model_haiku_id),
    ],
)
def test_pick_model_thresholds(projected: float, request_hint: str | None, expected: str) -> None:
    meter = _cost_meter(projected * settings.correlation_dollar_cap)

    result = pick_model(request_hint=request_hint, correlation_id="corr-1", cost_meter=meter)

    assert result == expected


@pytest.mark.parametrize(
    ("projected_pct", "downgrade_ok", "expected"),
    [
        # Below 25%: sonnet always honored, downgrade_ok irrelevant.
        (0.10, True, "sonnet"),
        (0.10, False, "sonnet"),
        # 25-70% band: downgrade_ok flips the outcome; silence keeps
        # phase-01's original binary behavior (sonnet stays).
        (0.50, False, "sonnet"),
        (0.50, True, "haiku"),
        (0.69, True, "haiku"),
        # Above 70%: haiku forced regardless of downgrade_ok.
        (0.71, True, "haiku"),
        (0.71, False, "haiku"),
    ],
)
def test_pick_model_downgrade_ok_tier(
    projected_pct: float, downgrade_ok: bool, expected: str
) -> None:
    meter = _cost_meter(projected_pct * settings.correlation_dollar_cap)
    expected_id = settings.model_sonnet_id if expected == "sonnet" else settings.model_haiku_id

    result = pick_model(
        request_hint="sonnet",
        correlation_id="corr-1",
        cost_meter=meter,
        downgrade_ok=downgrade_ok,
    )

    assert result == expected_id
