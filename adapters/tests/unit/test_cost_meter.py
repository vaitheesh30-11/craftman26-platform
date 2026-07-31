from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest
from aws_lambda_powertools import Metrics

from iam_sentinel_adapters.cost_meter import CostMeter, SpendKind
from iam_sentinel_adapters.errors import BudgetExceededError

if TYPE_CHECKING:
    import boto3
    from mypy_boto3_dynamodb.service_resource import Table


def _meter(budget_table: Table, ssm_client: boto3.client) -> CostMeter:
    return CostMeter(table=budget_table, ssm_client=ssm_client, metrics=Metrics(namespace="Test"))


def test_record_and_projected_accumulate(budget_table: Table, ssm_client: boto3.client) -> None:
    meter = _meter(budget_table, ssm_client)
    meter.record("corr-1", SpendKind.BEDROCK_TOKENS, 10.0)
    meter.record("corr-1", SpendKind.BEDROCK_TOKENS, 5.0)

    assert meter.projected("corr-1") == 15.0


def test_concurrent_records_yield_accurate_total(budget_table: Table, ssm_client: boto3.client) -> None:
    meter = _meter(budget_table, ssm_client)

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda _: meter.record("corr-concurrent", SpendKind.BEDROCK_TOKENS, 1.0), range(100)))

    assert meter.projected("corr-concurrent") == 100.0


def test_check_budget_raises_when_cap_exceeded(budget_table: Table, ssm_client: boto3.client) -> None:
    ssm_client.put_parameter(
        Name="/sentinel/budget/bedrock_tokens", Value="10", Type="String"
    )
    meter = _meter(budget_table, ssm_client)
    meter.record("corr-2", SpendKind.BEDROCK_TOKENS, 8.0)

    with pytest.raises(BudgetExceededError):
        meter.check_budget("corr-2", SpendKind.BEDROCK_TOKENS, 5.0)


def test_check_budget_passes_within_cap(budget_table: Table, ssm_client: boto3.client) -> None:
    ssm_client.put_parameter(
        Name="/sentinel/budget/bedrock_tokens", Value="100", Type="String"
    )
    meter = _meter(budget_table, ssm_client)
    meter.record("corr-3", SpendKind.BEDROCK_TOKENS, 8.0)

    meter.check_budget("corr-3", SpendKind.BEDROCK_TOKENS, 5.0)


def test_record_persists_attribution_fields(budget_table: Table, ssm_client: boto3.client) -> None:
    """agents-phase-16 §7 (docs/decisions/0032): a weekly cost report needs
    feature_id/principal/mode on every sample, not just as EMF dimensions
    that age out of CloudWatch -- `samples()` is the read path the report
    Lambda and `budget_gate` use.
    """
    meter = _meter(budget_table, ssm_client)
    meter.record(
        "corr-attrib",
        SpendKind.BEDROCK_DOLLARS,
        0.02,
        feature_id="F1",
        principal="arn:aws:iam::111122223333:user/auditor",
        mode="fast",
    )

    rows = meter.samples("corr-attrib")

    assert len(rows) == 1
    assert rows[0]["feature_id"] == "F1"
    assert rows[0]["principal"] == "arn:aws:iam::111122223333:user/auditor"
    assert rows[0]["mode"] == "fast"
    assert rows[0]["kind"] == SpendKind.BEDROCK_DOLLARS.value


def test_samples_returns_empty_list_for_unknown_correlation(
    budget_table: Table, ssm_client: boto3.client
) -> None:
    meter = _meter(budget_table, ssm_client)

    assert meter.samples("no-such-correlation") == []
