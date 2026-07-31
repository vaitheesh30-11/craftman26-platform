from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
from iam_sentinel_adapters.cost_meter import CostMeter, SpendKind
from iam_sentinel_adapters.errors import BudgetExceededError, CircuitOpenError

from iam_sentinel_agents.tools.common import budget_gate

if TYPE_CHECKING:
    import boto3
    from mypy_boto3_dynamodb.service_resource import Table

_PRINCIPAL = "arn:aws:iam::111122223333:user/auditor"


def _meter(budget_table: Table, ssm_client: boto3.client) -> CostMeter:
    return CostMeter(table=budget_table, ssm_client=ssm_client)


def _breaker(breakers_table: Table) -> BreakerAccessor:
    return BreakerAccessor(table=breakers_table)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("fast", 0.001),
        ("slow_single", 0.10),
        ("slow_multi", 0.30),
    ],
)
def test_estimate_cost_matches_spec_heuristic(mode: budget_gate.InvocationMode, expected: float) -> None:
    assert budget_gate.estimate_cost(mode) == expected


def test_daily_principal_key_is_stable_for_the_same_day() -> None:
    day = date(2026, 7, 31)

    key_a = budget_gate.daily_principal_key(_PRINCIPAL, day)
    key_b = budget_gate.daily_principal_key(_PRINCIPAL, day)

    assert key_a == key_b
    assert key_a == f"daily#{_PRINCIPAL}#2026-07-31"


def test_check_startable_passes_under_every_cap(
    budget_table: Table, breakers_table: Table, ssm_client: boto3.client
) -> None:
    ssm_client.put_parameter(Name="/sentinel/budget/bedrock_dollars", Value="1.0", Type="String")
    ssm_client.put_parameter(
        Name="/sentinel/budget/principal_daily_dollars", Value="50.0", Type="String"
    )
    meter = _meter(budget_table, ssm_client)
    breaker = _breaker(breakers_table)

    budget_gate.check_startable(
        correlation_id="corr-1",
        principal=_PRINCIPAL,
        mode="fast",
        cost_meter=meter,
        breaker=breaker,
    )


def test_check_startable_raises_when_circuit_open(
    budget_table: Table, breakers_table: Table, ssm_client: boto3.client
) -> None:
    meter = _meter(budget_table, ssm_client)
    breaker = _breaker(breakers_table)
    breaker.trip("bedrock", "3 throttles within 60s")

    with pytest.raises(CircuitOpenError):
        budget_gate.check_startable(
            correlation_id="corr-2",
            principal=_PRINCIPAL,
            mode="fast",
            cost_meter=meter,
            breaker=breaker,
        )


def test_check_startable_raises_when_daily_principal_cap_exceeded(
    budget_table: Table, breakers_table: Table, ssm_client: boto3.client
) -> None:
    ssm_client.put_parameter(Name="/sentinel/budget/bedrock_dollars", Value="1.0", Type="String")
    ssm_client.put_parameter(
        Name="/sentinel/budget/principal_daily_dollars", Value="0.05", Type="String"
    )
    meter = _meter(budget_table, ssm_client)
    breaker = _breaker(breakers_table)
    day = date(2026, 7, 31)
    meter.record(
        budget_gate.daily_principal_key(_PRINCIPAL, day),
        SpendKind.PRINCIPAL_DAILY_DOLLARS,
        0.049,
    )

    with pytest.raises(BudgetExceededError):
        budget_gate.check_startable(
            correlation_id="corr-3",
            principal=_PRINCIPAL,
            mode="slow_multi",
            cost_meter=meter,
            breaker=breaker,
            day=day,
        )


def test_check_startable_raises_when_correlation_cap_exceeded(
    budget_table: Table, breakers_table: Table, ssm_client: boto3.client
) -> None:
    ssm_client.put_parameter(Name="/sentinel/budget/bedrock_dollars", Value="0.05", Type="String")
    ssm_client.put_parameter(
        Name="/sentinel/budget/principal_daily_dollars", Value="50.0", Type="String"
    )
    meter = _meter(budget_table, ssm_client)
    breaker = _breaker(breakers_table)
    meter.record("corr-4", SpendKind.BEDROCK_DOLLARS, 0.049)

    with pytest.raises(BudgetExceededError):
        budget_gate.check_startable(
            correlation_id="corr-4",
            principal=_PRINCIPAL,
            mode="slow_multi",
            cost_meter=meter,
            breaker=breaker,
        )


def test_record_startup_spend_writes_both_ledgers(
    budget_table: Table, ssm_client: boto3.client
) -> None:
    meter = _meter(budget_table, ssm_client)
    day = date(2026, 7, 31)

    budget_gate.record_startup_spend(
        correlation_id="corr-5",
        principal=_PRINCIPAL,
        mode="slow_single",
        cost_meter=meter,
        feature_id="F1",
        day=day,
    )

    assert meter.projected("corr-5") == pytest.approx(0.10)
    daily_key = budget_gate.daily_principal_key(_PRINCIPAL, day)
    assert meter.projected(daily_key) == pytest.approx(0.10)


def test_runaway_agent_halted_at_tool_invocation_cap(
    budget_table: Table, ssm_client: boto3.client
) -> None:
    """phase-16 §8 acceptance criterion: "an agent tries to make 100
    Bedrock calls; halted at cap 30".
    """
    ssm_client.put_parameter(Name="/sentinel/budget/tool_invocations", Value="30", Type="String")
    meter = _meter(budget_table, ssm_client)

    allowed = 0
    for _ in range(100):
        try:
            budget_gate.check_tool_invocation_cap(correlation_id="corr-runaway", cost_meter=meter)
        except BudgetExceededError:
            break
        budget_gate.record_tool_invocation(correlation_id="corr-runaway", cost_meter=meter)
        allowed += 1

    assert allowed == 30
