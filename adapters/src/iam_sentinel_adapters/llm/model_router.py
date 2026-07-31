"""Haiku-default, Sonnet-on-demand, cost-aware downgrade (phase-01 §4
step 3; three-tier refinement per agents-phase-16 §5 step 8,
docs/decisions/0033). Downgrade always wins over an explicit Sonnet request
once a correlation is past 70% of its dollar cap -- staying on the cheaper
model is worth more than the caller's preference.

Three tiers (phase-16 §5 step 8):
  - < 25% of cap: `request_hint` is honored outright.
  - 25-70%: Sonnet is only downgraded to Haiku if the *specialist* has
    flagged its own task `downgrade_ok=True` -- a specialist that needs
    Sonnet's reasoning for a specific tool call can say so and keep it in
    this band. Silence (the default, `downgrade_ok=False`) preserves
    phase-01's original binary behavior exactly, which is why every one of
    phase-01's original six parametrized cases still passes unmodified.
  - > 70%: Haiku is forced regardless of `request_hint` or `downgrade_ok`
    -- past this point the caller's preference no longer matters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_adapters.cost_meter import CostMeter

_SONNET_ALLOWED_BELOW_PCT = 0.25
_DOWNGRADE_THRESHOLD_PCT = 0.70


def pick_model(
    *,
    request_hint: Literal["haiku", "sonnet"] | None,
    correlation_id: str,
    cost_meter: CostMeter,
    downgrade_ok: bool = False,
) -> str:
    spent = cost_meter.projected(correlation_id)
    cap = settings.correlation_dollar_cap
    pct = spent / cap if cap > 0 else 0.0

    if pct > _DOWNGRADE_THRESHOLD_PCT:
        return settings.model_haiku_id
    if request_hint != "sonnet":
        return settings.model_haiku_id
    if pct > _SONNET_ALLOWED_BELOW_PCT and downgrade_ok:
        return settings.model_haiku_id
    return settings.model_sonnet_id
