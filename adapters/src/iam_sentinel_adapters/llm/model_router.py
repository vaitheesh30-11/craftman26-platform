"""Haiku-default, Sonnet-on-demand, cost-aware downgrade (phase-01 §4
step 3). Downgrade always wins over an explicit Sonnet request -- once a
correlation is past 70% of its dollar cap, staying on the cheaper model is
worth more than the caller's preference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_adapters.cost_meter import CostMeter

_DOWNGRADE_THRESHOLD_PCT = 0.70


def pick_model(*, request_hint: Literal["haiku", "sonnet"] | None, correlation_id: str, cost_meter: CostMeter) -> str:
    spent = cost_meter.projected(correlation_id)
    cap = settings.correlation_dollar_cap
    pct = spent / cap if cap > 0 else 0.0

    if pct > _DOWNGRADE_THRESHOLD_PCT:
        return settings.model_haiku_id
    if request_hint == "sonnet":
        return settings.model_sonnet_id
    return settings.model_haiku_id
