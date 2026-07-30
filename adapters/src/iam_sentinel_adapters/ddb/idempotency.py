"""`SentinelIdempotency` table client (phase-01 §4 step 3) — Prime's
post-turn Lambda claims a `correlation_id` exactly once via a conditional
put; a retried EventBridge delivery or a duplicate `InvokeAgent` trace for
the same turn is rejected rather than re-running side effects (DDB write,
KMS-signed evidence, SNS/Security Hub publish) a second time.

This is a narrower primitive than `aws_lambda_powertools.utilities.
idempotency`'s persistence layer: it does not memoize/replay a handler's
return value, only the claim itself, which is all `PrimePostTurnProcessor`
needs. It goes through `DynamoDbHelper` like every other table client
(module boundary, adapters/README.md §1: boto3 only through adapters/) --
Powertools' own `DynamoDBPersistenceLayer` calls boto3 directly and would
bypass the retry/circuit-breaker/EMF wrapping the rest of this package
standardizes on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.errors import ValidationError
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_TTL_HOURS = 24


class IdempotencyClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(table_name or settings.idempotency_table, table=table, breaker=breaker)

    def claim(self, correlation_id: str) -> bool:
        """Attempt to claim `correlation_id`. Returns True on first claim,
        False if it was already claimed (the caller must skip re-running
        side effects, not treat this as an error).
        """
        expires_at = int((datetime.now(UTC) + timedelta(hours=_TTL_HOURS)).timestamp())
        try:
            self._helper.put_item(
                {"correlation_id": correlation_id, "claimed_at": datetime.now(UTC).isoformat(), "expires_at": expires_at},
                condition_expression="attribute_not_exists(correlation_id)",
            )
        except ValidationError:
            return False
        return True

    def already_claimed(self, correlation_id: str) -> bool:
        return self._helper.get_item({"correlation_id": correlation_id}) is not None
