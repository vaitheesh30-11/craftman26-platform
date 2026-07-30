"""Shared DynamoDB access primitives every table client wraps (phase-05
§6 step 1). Owns retry, circuit-breaking, and EMF read/write metrics so
individual table clients only need to know their own key shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit

from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
from iam_sentinel_adapters.errors import ThrottlingError, ValidationError
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


class DynamoDbHelper:
    def __init__(
        self,
        table_name: str,
        *,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._table_name = table_name
        self._table: Table = table or boto3.resource("dynamodb", region_name=settings.region).Table(
            table_name
        )
        self._breaker = breaker or BreakerAccessor()
        self._metrics = metrics or Metrics(namespace=settings.metric_namespace)

    def put_item(self, item: dict[str, Any], *, condition_expression: str | None = None) -> None:
        self._breaker.raise_if_open(self._table_name)
        try:
            self._write(item, condition_expression=condition_expression)
        except Exception:
            self._breaker.record_failure(self._table_name)
            raise
        self._breaker.record_success(self._table_name)
        self._metrics.add_metric(name="SentinelDdbWrites", unit=MetricUnit.Count, value=1)

    def delete_item(self, key: dict[str, Any]) -> None:
        self._breaker.raise_if_open(self._table_name)
        try:
            self._delete(key)
        except Exception:
            self._breaker.record_failure(self._table_name)
            raise
        self._breaker.record_success(self._table_name)
        self._metrics.add_metric(name="SentinelDdbWrites", unit=MetricUnit.Count, value=1)

    def get_item(self, key: dict[str, Any]) -> dict[str, Any] | None:
        self._breaker.raise_if_open(self._table_name)
        try:
            response = self._get(key)
        except Exception:
            self._breaker.record_failure(self._table_name)
            raise
        self._breaker.record_success(self._table_name)
        self._metrics.add_metric(name="SentinelDdbReads", unit=MetricUnit.Count, value=1)
        return response.get("Item")

    def query(
        self,
        *,
        key_condition_expression: str,
        expression_attribute_values: dict[str, Any],
        expression_attribute_names: dict[str, str] | None = None,
        index_name: str | None = None,
        limit: int = 100,
        scan_index_forward: bool = True,
    ) -> list[dict[str, Any]]:
        self._breaker.raise_if_open(self._table_name)
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": key_condition_expression,
            "ExpressionAttributeValues": expression_attribute_values,
            "Limit": limit,
            "ScanIndexForward": scan_index_forward,
        }
        if expression_attribute_names is not None:
            kwargs["ExpressionAttributeNames"] = expression_attribute_names
        if index_name is not None:
            kwargs["IndexName"] = index_name
        try:
            response = self._query(**kwargs)
        except Exception:
            self._breaker.record_failure(self._table_name)
            raise
        self._breaker.record_success(self._table_name)
        self._metrics.add_metric(name="SentinelDdbReads", unit=MetricUnit.Count, value=1)
        return list(response.get("Items", []))

    def query_page(
        self,
        *,
        key_condition_expression: str,
        expression_attribute_values: dict[str, Any],
        expression_attribute_names: dict[str, str] | None = None,
        filter_expression: str | None = None,
        index_name: str | None = None,
        limit: int = 100,
        scan_index_forward: bool = True,
        exclusive_start_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Like `query`, but also returns `LastEvaluatedKey` (opaque, caller
        base64-encodes it as `next_token`) for backend REST pagination
        (backend phase-01 §6) -- `query` alone discards it because no caller
        needed multi-page reads before this phase.
        """
        self._breaker.raise_if_open(self._table_name)
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": key_condition_expression,
            "ExpressionAttributeValues": expression_attribute_values,
            "Limit": limit,
            "ScanIndexForward": scan_index_forward,
        }
        if expression_attribute_names is not None:
            kwargs["ExpressionAttributeNames"] = expression_attribute_names
        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression
        if index_name is not None:
            kwargs["IndexName"] = index_name
        if exclusive_start_key is not None:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        try:
            response = self._query(**kwargs)
        except Exception:
            self._breaker.record_failure(self._table_name)
            raise
        self._breaker.record_success(self._table_name)
        self._metrics.add_metric(name="SentinelDdbReads", unit=MetricUnit.Count, value=1)
        return list(response.get("Items", [])), response.get("LastEvaluatedKey")

    def scan_page(
        self,
        *,
        filter_expression: str | None = None,
        expression_attribute_values: dict[str, Any] | None = None,
        expression_attribute_names: dict[str, str] | None = None,
        limit: int = 100,
        exclusive_start_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Bounded fallback read path for filters that have no covering index
        (backend phase-01 §6) -- correctness over efficiency for the handful
        of query shapes no GSI was provisioned for; callers cap the number of
        pages they walk rather than looping unbounded.
        """
        self._breaker.raise_if_open(self._table_name)
        kwargs: dict[str, Any] = {"Limit": limit}
        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression
        if expression_attribute_values is not None:
            kwargs["ExpressionAttributeValues"] = expression_attribute_values
        if expression_attribute_names is not None:
            kwargs["ExpressionAttributeNames"] = expression_attribute_names
        if exclusive_start_key is not None:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        try:
            response = self._scan(**kwargs)
        except Exception:
            self._breaker.record_failure(self._table_name)
            raise
        self._breaker.record_success(self._table_name)
        self._metrics.add_metric(name="SentinelDdbReads", unit=MetricUnit.Count, value=1)
        return list(response.get("Items", [])), response.get("LastEvaluatedKey")

    def update_item(
        self,
        key: dict[str, Any],
        *,
        update_expression: str,
        expression_attribute_values: dict[str, Any],
        expression_attribute_names: dict[str, str] | None = None,
        condition_expression: str | None = None,
    ) -> None:
        self._breaker.raise_if_open(self._table_name)
        try:
            self._update(
                key,
                update_expression=update_expression,
                expression_attribute_values=expression_attribute_values,
                expression_attribute_names=expression_attribute_names,
                condition_expression=condition_expression,
            )
        except Exception:
            self._breaker.record_failure(self._table_name)
            raise
        self._breaker.record_success(self._table_name)
        self._metrics.add_metric(name="SentinelDdbWrites", unit=MetricUnit.Count, value=1)

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _write(self, item: dict[str, Any], *, condition_expression: str | None) -> None:
        kwargs: dict[str, Any] = {"Item": item}
        if condition_expression is not None:
            kwargs["ConditionExpression"] = condition_expression
        try:
            self._table.put_item(**kwargs)
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ValidationError(f"conditional put failed for {self._table_name}") from None
        except self._table.meta.client.exceptions.ProvisionedThroughputExceededException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _delete(self, key: dict[str, Any]) -> None:
        try:
            self._table.delete_item(Key=key)
        except self._table.meta.client.exceptions.ProvisionedThroughputExceededException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _get(self, key: dict[str, Any]) -> dict[str, Any]:
        try:
            return dict(self._table.get_item(Key=key))
        except self._table.meta.client.exceptions.ProvisionedThroughputExceededException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _query(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._table.query(**kwargs))
        except self._table.meta.client.exceptions.ProvisionedThroughputExceededException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _scan(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._table.scan(**kwargs))
        except self._table.meta.client.exceptions.ProvisionedThroughputExceededException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _update(
        self,
        key: dict[str, Any],
        *,
        update_expression: str,
        expression_attribute_values: dict[str, Any],
        expression_attribute_names: dict[str, str] | None,
        condition_expression: str | None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "Key": key,
            "UpdateExpression": update_expression,
            "ExpressionAttributeValues": expression_attribute_values,
        }
        if expression_attribute_names is not None:
            kwargs["ExpressionAttributeNames"] = expression_attribute_names
        if condition_expression is not None:
            kwargs["ConditionExpression"] = condition_expression
        try:
            self._table.update_item(**kwargs)
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ValidationError(f"conditional update failed for {self._table_name}") from None
        except self._table.meta.client.exceptions.ProvisionedThroughputExceededException as exc:
            raise ThrottlingError(str(exc)) from exc
