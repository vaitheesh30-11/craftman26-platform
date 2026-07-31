#!/usr/bin/env python3
"""Quarterly game-day failover drill (agents phase-17 §9, §12).

Reports the real state of every §9 region-failover signal available in
the current AWS account -- Route 53 health check status for Prime's API,
and DDB global-table replication status for the four cross-region tables
§9 names. Anything not yet provisioned (no standby region exists as of
this phase; see `docs/decisions/0032`) is reported as `NOT_PROVISIONED`,
not fabricated as a passing check.

Not under `src/iam_sentinel_agents` (outside the package's coverage
scope, same convention as `backend/scripts`/`frontend/scripts`) -- this is
an operator tool, not library code another module imports.

Usage: `python agents/scripts/gameday_failover.py [--region us-east-1]`
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_route53.client import Route53Client

_CROSS_REGION_GLOBAL_TABLES = (
    "SentinelFindings",
    "SentinelDecisions",
    "SentinelMemoryEpisodic",
    "SentinelPolicies",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "OK" | "DEGRADED" | "NOT_PROVISIONED" | "ERROR"
    detail: str


@dataclass(frozen=True)
class GamedayReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_provisioned_and_healthy(self) -> bool:
        return all(check.status == "OK" for check in self.checks)


def check_route53_health_check(
    *, health_check_id: str, route53_client: Route53Client | None = None
) -> CheckResult:
    if not health_check_id:
        return CheckResult(
            name="route53_health_check",
            status="NOT_PROVISIONED",
            detail="no health_check_id configured -- Prime's failover health check "
            "has not been provisioned yet",
        )
    import boto3

    client: Route53Client = route53_client or boto3.client("route53")
    try:
        response = client.get_health_check_status(HealthCheckId=health_check_id)
    except Exception as exc:  # noqa: BLE001 -- operator tool, report don't crash
        return CheckResult(
            name="route53_health_check", status="ERROR", detail=f"{type(exc).__name__}: {exc}"
        )

    observations = response.get("HealthCheckObservations", [])
    healthy = any(
        observation.get("StatusReport", {}).get("Status", "").startswith("Success")
        for observation in observations
    )
    return CheckResult(
        name="route53_health_check",
        status="OK" if healthy else "DEGRADED",
        detail=f"{len(observations)} observation(s), healthy={healthy}",
    )


def check_global_table_replication(
    table_name: str, *, dynamodb_client: DynamoDBClient | None = None
) -> CheckResult:
    import boto3

    client: DynamoDBClient = dynamodb_client or boto3.client("dynamodb")
    try:
        response = client.describe_table(TableName=table_name)
    except Exception as exc:  # noqa: BLE001 -- operator tool, report don't crash
        return CheckResult(
            name=f"global_table:{table_name}", status="ERROR", detail=f"{type(exc).__name__}: {exc}"
        )

    replicas = response["Table"].get("Replicas", [])
    if not replicas:
        return CheckResult(
            name=f"global_table:{table_name}",
            status="NOT_PROVISIONED",
            detail="no cross-region replica configured -- table is single-region",
        )

    unhealthy = [r for r in replicas if r.get("ReplicaStatus") != "ACTIVE"]
    if unhealthy:
        return CheckResult(
            name=f"global_table:{table_name}",
            status="DEGRADED",
            detail=f"{len(unhealthy)}/{len(replicas)} replica(s) not ACTIVE",
        )
    return CheckResult(
        name=f"global_table:{table_name}",
        status="OK",
        detail=f"{len(replicas)} replica(s) ACTIVE",
    )


def run_gameday_drill(
    *,
    health_check_id: str = "",
    route53_client: Route53Client | None = None,
    dynamodb_client: DynamoDBClient | None = None,
    table_names: tuple[str, ...] = _CROSS_REGION_GLOBAL_TABLES,
) -> GamedayReport:
    checks = [
        check_route53_health_check(health_check_id=health_check_id, route53_client=route53_client),
        *(
            check_global_table_replication(table_name, dynamodb_client=dynamodb_client)
            for table_name in table_names
        ),
    ]
    return GamedayReport(checks=checks)


def _report_as_dict(report: GamedayReport) -> dict[str, Any]:
    return {
        "all_provisioned_and_healthy": report.all_provisioned_and_healthy,
        "checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in report.checks],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-check-id", default="", help="Route 53 health check ID")
    args = parser.parse_args(argv)

    report = run_gameday_drill(health_check_id=args.health_check_id)
    print(json.dumps(_report_as_dict(report), indent=2))
    return 0 if report.all_provisioned_and_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
