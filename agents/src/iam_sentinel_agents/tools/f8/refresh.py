"""slr_db_refresh -- weekly maintenance Lambda (phase-09 §4 Step 2).

Enumerates AWS-managed Service-Linked Role policies via IAM read APIs,
merges each with the curated seed dataset (`agents/data/slr_seed.json`),
and writes the result to `SentinelSLRs` via `SlrsClient`. Not an
agent-callable action-group tool (§3: "scheduled, not agent-callable") --
no `sentinel_handler` envelope, just a plain EventBridge-scheduled Lambda
handler.

boto3 IAM calls happen directly here, not through `cross_account.assume()`:
Service-Linked Role policies are AWS-managed and identical across every
account, and this Lambda always runs with the Sentinel platform account's
own execution role, never a member account's -- contrast with
`tools/f1/scan.py`, which reads a *specific member account's* IAM state and
therefore needs `cross_account.assume()`. No adapter wraps IAM read APIs
(see `tools/f8/scan.py`'s own module docstring), so this is the same
deliberate, documented exception to "boto3 only through adapters/" that F1
already established (agents/README.md §1).
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, TYPE_CHECKING

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from iam_sentinel_adapters.ddb.slrs import SlrsClient

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_iam.client import IAMClient

_SEED_PATH = Path(__file__).resolve().parents[4] / "data" / "slr_seed.json"
_SLR_POLICY_PREFIX = "AWSServiceRoleFor"
_COMPARABLE_ROW_KEYS = ("slr_name", "required_actions", "optional_actions", "core_actions")

_logger = Logger(service="iam-sentinel-f8-refresh")
_metrics = Metrics(namespace="IAMSentinel", service="iam-sentinel-f8-refresh")


def load_seed(path: Path = _SEED_PATH) -> dict[str, dict[str, Any]]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _normalize_policy_document(raw: Any) -> dict[str, Any]:
    """IAM's `PolicyDocument`/`Document` response fields are typed
    `str | PolicyDocumentDictTypeDef` in the boto3 stubs -- botocore's own
    IAM customization JSON-decodes them in practice, but the stub can't
    promise that (same shape of gap `tools/f1/scan.py::normalize_policy_
    document` already documents for `passrole_scan`).
    """
    if isinstance(raw, str):
        return dict(json.loads(raw))
    return dict(raw)


def _statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    statement = document.get("Statement", [])
    return [statement] if isinstance(statement, dict) else list(statement)


def _allow_actions_from_policy(
    iam: IAMClient, policy_arn: str, default_version_id: str
) -> list[str]:
    version = iam.get_policy_version(PolicyArn=policy_arn, VersionId=default_version_id)
    document = _normalize_policy_document(version["PolicyVersion"]["Document"])
    actions: set[str] = set()
    for statement in _statements(document):
        if statement.get("Effect") != "Allow":
            continue
        raw_actions = statement.get("Action", [])
        actions.update([raw_actions] if isinstance(raw_actions, str) else raw_actions)
    return sorted(actions)


def enumerate_live_actions(
    iam: IAMClient, seed: dict[str, dict[str, Any]], *, scope: str = "AWS"
) -> dict[str, list[str]]:
    """`slr_name -> live Allow actions` for every AWS-managed
    `AWSServiceRoleFor*` policy IAM returns whose name the seed dataset
    already maps to a service principal. A policy IAM returns that the
    seed doesn't recognize is a genuine drift signal (a new SLR AWS
    shipped) -- logged, not silently merged, since only the seed carries
    the service-principal mapping (phase-09 §4 Step 2).

    `scope` defaults to `"AWS"` per §4 Step 2's own wording
    (`iam:ListPolicies(Scope="AWS")`) but is overridable: moto's IAM mock
    cannot fabricate real AWS-managed `AWSServiceRoleFor*` policies, so
    tests inject `scope="Local"` against a customer-managed policy to
    exercise the same pagination/parsing path (docs/decisions/0023).
    """
    known_slr_names = {row["slr_name"] for row in seed.values()}
    live: dict[str, list[str]] = {}
    for page in iam.get_paginator("list_policies").paginate(Scope=scope):  # type: ignore[arg-type]
        for policy in page["Policies"]:
            policy_name = policy["PolicyName"]
            if not policy_name.startswith(_SLR_POLICY_PREFIX):
                continue
            if policy_name not in known_slr_names:
                _logger.warning("unrecognized_slr_policy", policy_name=policy_name)
                continue
            live[policy_name] = _allow_actions_from_policy(
                iam, policy["Arn"], policy["DefaultVersionId"]
            )
    return live


def merge_with_seed(
    seed: dict[str, dict[str, Any]], live_actions_by_slr_name: dict[str, list[str]]
) -> dict[str, dict[str, Any]]:
    """Per phase-09 §4 Step 2: union the seed's curated `required_actions`
    with whatever the live policy currently allows, keyed by service
    principal (the seed's PK, per §3's DDB schema).
    """
    merged: dict[str, dict[str, Any]] = {}
    for principal, row in seed.items():
        live_actions = live_actions_by_slr_name.get(row["slr_name"], [])
        required_actions = sorted(set(row.get("required_actions", [])) | set(live_actions))
        merged[principal] = {
            "service_principal": principal,
            "slr_name": row["slr_name"],
            "required_actions": required_actions,
            "optional_actions": row.get("optional_actions", []),
            "core_actions": row.get("core_actions", []),
            "source": row.get("source", ""),
            "source_url": row.get("source_url", ""),
        }
    return merged


def _row_changed(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> bool:
    if existing is None:
        return True
    return any(existing.get(key) != candidate.get(key) for key in _COMPARABLE_ROW_KEYS)


def refresh_slr_db(
    *,
    iam: IAMClient,
    slrs_client: SlrsClient,
    seed: dict[str, dict[str, Any]],
    last_updated: str,
    scope: str = "AWS",
) -> dict[str, Any]:
    """Core refresh logic (phase-09 §4 Step 2), independent of the Lambda
    envelope -- `iam`/`slrs_client`/`scope` are injection points for tests.
    """
    live_actions = enumerate_live_actions(iam, seed, scope=scope)
    merged_rows = merge_with_seed(seed, live_actions)

    existing_rows = {row["service_principal"]: row for row in slrs_client.list_all()}
    current_version = max(
        (int(row.get("db_version", 0)) for row in existing_rows.values()), default=0
    )
    changed = any(
        _row_changed(existing_rows.get(principal), row) for principal, row in merged_rows.items()
    )
    new_version = str(current_version + 1) if changed else str(current_version)

    for row in merged_rows.values():
        slrs_client.put({**row, "db_version": new_version, "last_updated": last_updated})

    _metrics.add_metric(name="SentinelSlrDbSize", unit=MetricUnit.Count, value=len(merged_rows))

    return {"db_version": new_version, "slr_count": len(merged_rows), "changed": changed}


@_metrics.log_metrics
def slr_db_refresh(_event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    iam: IAMClient = boto3.client("iam")
    result = refresh_slr_db(
        iam=iam,
        slrs_client=SlrsClient(),
        seed=load_seed(),
        last_updated=datetime.now(UTC).date().isoformat(),
    )
    _logger.info("slr_db_refresh_completed", **result)
    return result
