"""`SentinelFindings` table client (phase-05 §3-4).

Key attributes use the `#`-joined composite convention established in
aws-infra ADR 0005: `account_id#feature_id` (PK), `finding_id#detected_at`
(SK). Every expression below must alias them via `ExpressionAttributeNames`
-- DynamoDB's expression grammar treats a bare `#` as a name-placeholder
marker, so a literal `#` inside an unaliased attribute name breaks parsing.

Callers pass and receive plain dicts, never an agents `Finding` model —
adapters does not import from `agents/` (module boundary, README §1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from datetime import datetime

    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_PK_ATTR = "account_id#feature_id"
_SK_ATTR = "finding_id#detected_at"
_GSI_SEVERITY = "severity-index"
_MAX_SCAN_PAGES = 10  # bounded fallback for filter combinations no GSI covers


class FindingsClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.findings_table, table=table, breaker=breaker
        )

    def put(self, finding: dict[str, Any]) -> None:
        item = {
            **finding,
            _PK_ATTR: f"{finding['account_id']}#{finding['feature_id']}",
            _SK_ATTR: f"{finding['finding_id']}#{finding['detected_at']}",
        }
        self._helper.put_item(item)

    def get(self, account_id: str, feature_id: str, finding_id: str) -> dict[str, Any] | None:
        matches = self._helper.query(
            key_condition_expression="#pk = :pk AND begins_with(#sk, :prefix)",
            expression_attribute_names={"#pk": _PK_ATTR, "#sk": _SK_ATTR},
            expression_attribute_values={
                ":pk": f"{account_id}#{feature_id}",
                ":prefix": f"{finding_id}#",
            },
            limit=1,
        )
        return matches[0] if matches else None

    def query_by_severity(
        self, severity: str, since: datetime, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._helper.query(
            key_condition_expression="severity = :sev AND detected_at >= :since",
            expression_attribute_values={":sev": severity, ":since": since.isoformat()},
            index_name="severity-index",
            limit=limit,
        )

    def get_by_id(self, finding_id: str) -> dict[str, Any] | None:
        """`GET /findings/{id}` (backend phase-01 §6): no GSI is keyed on
        `finding_id` alone (only `severity-index` and `feature-status-index`
        exist, per `aws-infra`'s `foundation_stack.py`), so a bare id lookup
        is a bounded scan filtered on the SK's `finding_id#` prefix. Callers
        that already know `account_id`/`feature_id` (e.g. from a prior
        `/findings` list page) should call `get()` instead -- that's a real
        `Query`, not a scan.
        """
        prefix = f"{finding_id}#"
        exclusive_start_key: dict[str, Any] | None = None
        for _ in range(_MAX_SCAN_PAGES):
            items, exclusive_start_key = self._helper.scan_page(
                filter_expression="begins_with(#sk, :prefix)",
                expression_attribute_values={":prefix": prefix},
                expression_attribute_names={"#sk": _SK_ATTR},
                limit=100,
                exclusive_start_key=exclusive_start_key,
            )
            if items:
                return items[0]
            if exclusive_start_key is None:
                break
        return None

    def list_page(
        self,
        *,
        account_id: str | None = None,
        feature_id: str | None = None,
        severity: str | None = None,
        principal_arn: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        exclusive_start_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Index-aware read for `GET /findings` (backend phase-01 §6).
        Picks the most selective available index for the given filters and
        pushes the rest down as a `FilterExpression`; falls back to a
        bounded scan when neither `account_id`+`feature_id` nor `severity`
        narrows the read (no GSI is keyed on `feature_id`/`principal_arn`
        alone).
        """
        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        filters: list[str] = []

        def _push_filter(attr: str, value: str | None, alias: str) -> None:
            if value is None:
                return
            names[f"#{alias}"] = attr
            values[f":{alias}"] = value
            filters.append(f"#{alias} = :{alias}")

        if account_id is not None and feature_id is not None:
            # The main table's SK (`finding_id#detected_at`) is keyed on
            # finding_id first, not detected_at -- it cannot express a date
            # range, so `since` here is a `FilterExpression`, not a `Query`
            # sort-key condition (unlike the `severity-index` branch below,
            # whose sort key genuinely is `detected_at`).
            _push_filter("severity", severity, "sev")
            _push_filter("principal_arn", principal_arn, "parn")
            if since is not None:
                names["#da"] = "detected_at"
                values[":since"] = since.isoformat()
                filters.append("#da >= :since")
            names["#pk"] = _PK_ATTR
            values[":pk"] = f"{account_id}#{feature_id}"
            return self._helper.query_page(
                key_condition_expression="#pk = :pk",
                expression_attribute_values=values,
                expression_attribute_names=names,
                filter_expression=" AND ".join(filters) or None,
                limit=limit,
                exclusive_start_key=exclusive_start_key,
            )

        if severity is not None:
            _push_filter("feature_id", feature_id, "fid")
            _push_filter("account_id", account_id, "aid")
            _push_filter("principal_arn", principal_arn, "parn")
            key_condition = "#sev = :sev"
            names["#sev"] = "severity"
            values[":sev"] = severity
            if since is not None:
                key_condition += " AND #da >= :since"
                names["#da"] = "detected_at"
                values[":since"] = since.isoformat()
            return self._helper.query_page(
                key_condition_expression=key_condition,
                expression_attribute_values=values,
                expression_attribute_names=names,
                filter_expression=" AND ".join(filters) or None,
                index_name=_GSI_SEVERITY,
                limit=limit,
                scan_index_forward=False,
                exclusive_start_key=exclusive_start_key,
            )

        _push_filter("feature_id", feature_id, "fid")
        _push_filter("account_id", account_id, "aid")
        _push_filter("principal_arn", principal_arn, "parn")
        if since is not None:
            names["#da"] = "detected_at"
            values[":since"] = since.isoformat()
            filters.append("#da >= :since")
        return self._helper.scan_page(
            filter_expression=" AND ".join(filters) if filters else None,
            expression_attribute_values=values or None,
            expression_attribute_names=names or None,
            limit=limit,
            exclusive_start_key=exclusive_start_key,
        )

    def update_status(self, account_id: str, feature_id: str, finding_id: str, status: str) -> None:
        existing = self.get(account_id, feature_id, finding_id)
        if existing is None:
            raise KeyError(f"no finding {finding_id!r} for {account_id}/{feature_id}")

        self._helper.update_item(
            {_PK_ATTR: existing[_PK_ATTR], _SK_ATTR: existing[_SK_ATTR]},
            update_expression="SET #status = :status",
            expression_attribute_names={"#status": "status"},
            expression_attribute_values={":status": status},
        )
