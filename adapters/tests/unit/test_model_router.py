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
