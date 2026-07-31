"""`SentinelDivergence` table client (backend phase-04 §2/§4 -- `GET
/operations/divergence`). Same on-demand precedent as `faults.py`: added
because this phase's read endpoint needs it, not one of the 3 representative
clients ADR 0006 originally scoped. Key shape per `aws-infra`'s
`foundation_stack.py` `_TableSpec("SentinelDivergence", pk="correlation_id",
sk="detected_at", gsis=(_Gsi("feature-divergence-index", pk="feature_id",
sk="divergence_kind"),))` -- the table is real (aws-infra phase-02), but no
producer exists yet: `DivergenceRecord`'s contract lives in `agents/docs/
phase-15-dual-mode-execution.txt §5` (dual-mode execution, not yet built,
Wave 8) and does not itself carry a `feature_id` field. This client stores
and reads plain dicts, same module-boundary rule as every other DDB client
here, so that gap is the future producer's problem, not this reader's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from datetime import datetime

    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_GSI_FEATURE_DIVERGENCE = "feature-divergence-index"


class DivergenceClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.divergence_table, table=table, breaker=breaker
        )

    def put(self, divergence: dict[str, Any]) -> None:
        self._helper.put_item(divergence)

    def list_recent(
        self,
        *,
        feature_id: str | None = None,
        divergence_kind: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        exclusive_start_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Filters per backend phase-04 §4 step 2: `feature_id` (queries the
        GSI, optionally narrowed to an exact `divergence_kind`), else a
        bounded scan filtered by `since` -- same fallback shape as
        `FaultsClient.list_recent` for the no-index-narrowing case.
        """
        if feature_id is not None:
            values: dict[str, Any] = {":fid": feature_id}
            condition = "#fid = :fid"
            if divergence_kind is not None:
                condition += " AND #dk = :dk"
                values[":dk"] = divergence_kind
            filter_expression = None
            names = {"#fid": "feature_id", "#dk": "divergence_kind"}
            if since is not None:
                filter_expression = "#da >= :since"
                values[":since"] = since.isoformat()
                names["#da"] = "detected_at"
            return self._helper.query_page(
                key_condition_expression=condition,
                expression_attribute_values=values,
                expression_attribute_names=names,
                filter_expression=filter_expression,
                index_name=_GSI_FEATURE_DIVERGENCE,
                limit=limit,
                scan_index_forward=False,
                exclusive_start_key=exclusive_start_key,
            )

        if since is None:
            return self._helper.scan_page(limit=limit, exclusive_start_key=exclusive_start_key)

        return self._helper.scan_page(
            filter_expression="#da >= :since",
            expression_attribute_values={":since": since.isoformat()},
            expression_attribute_names={"#da": "detected_at"},
            limit=limit,
            exclusive_start_key=exclusive_start_key,
        )
