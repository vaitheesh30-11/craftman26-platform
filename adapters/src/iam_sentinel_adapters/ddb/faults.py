"""`SentinelFaults` table client (backend phase-01 §7 -- `GET
/operations/faults`). Not one of the 3 representative clients ADR 0006
originally scoped; added on-demand per the ADR's own precedent since this
phase's read endpoint needs it. Key shape per `aws-infra`'s
`foundation_stack.py` `_TableSpec("SentinelFaults", pk="correlation_id",
sk="detected_at", gsis=(_Gsi("fault-class-index", pk="fault_class",
sk="detected_at"),))` -- the `FaultRecord` contract itself lives in
`agents/docs/phase-17-self-healing.txt §10` (self-healing, not yet built;
this client only stores/reads plain dicts, same module-boundary rule as
every other DDB client here).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from datetime import datetime

    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_GSI_FAULT_CLASS = "fault-class-index"
_MAX_SCAN_PAGES = 10  # bounded fallback when no `fault_class` filter narrows the read


class FaultsClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.faults_table, table=table, breaker=breaker
        )

    def put(self, fault: dict[str, Any]) -> None:
        self._helper.put_item(fault)

    def list_recent(
        self,
        *,
        fault_class: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        exclusive_start_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Filters per backend phase-01 §7: `fault_class`, `since`."""
        if fault_class is not None:
            values: dict[str, Any] = {":fc": fault_class}
            condition = "#fc = :fc"
            if since is not None:
                condition += " AND #da >= :since"
                values[":since"] = since.isoformat()
            return self._helper.query_page(
                key_condition_expression=condition,
                expression_attribute_values=values,
                expression_attribute_names={"#fc": "fault_class", "#da": "detected_at"},
                index_name=_GSI_FAULT_CLASS,
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
