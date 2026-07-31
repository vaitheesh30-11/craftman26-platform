from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.divergence import DivergenceClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def _divergence(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "correlation_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "feature_id": "F1",
        "divergence_kind": "material_disagreement",
        "diff_summary": "fast path missed an edge",
        "reviewed": False,
        "detected_at": "2026-07-30T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_put_then_list_by_feature_id(
    divergence_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DivergenceClient(table=divergence_table, breaker=moto_breaker)
    client.put(_divergence())
    client.put(_divergence(correlation_id="other", feature_id="F2"))

    items, next_key = client.list_recent(feature_id="F1")

    assert len(items) == 1
    assert items[0]["divergence_kind"] == "material_disagreement"
    assert next_key is None


def test_list_recent_with_no_filters_scans_everything(
    divergence_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DivergenceClient(table=divergence_table, breaker=moto_breaker)
    client.put(_divergence())

    items, _ = client.list_recent()

    assert len(items) == 1
