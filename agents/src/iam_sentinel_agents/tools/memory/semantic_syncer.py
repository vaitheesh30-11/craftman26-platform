"""`memory_semantic_syncer` -- hourly EventBridge-triggered Lambda that
refreshes `SentinelMemorySemantic` from live AWS org topology (phase-14
§3.3/§Step4).

Scope note (mirrors `docs/decisions/0006`'s own precedent -- "add each on
-demand when the specialist... that actually needs it lands, rather than
guessing its query shape now"): phase-14 §3.3 lists six entity syncers
(accounts, OUs, roles, permission sets, service principals, policies).
This module fully implements the two whose source APIs are already used
elsewhere in this codebase and therefore have a real, previously-verified
call shape to build against -- `organizations:ListAccounts` (accounts) and
`sso-admin:ListPermissionSets`/`DescribePermissionSet` (permission sets).
Roles are "enumerated during F1 scans; refreshed opportunistically" per
spec -- i.e. driven by F1's own pipeline, not this syncer. OUs, service
principals (seeded from F8's SLR DB), and policies (cached during F4/F7
walks) each need a shape only their owning phase's already-built client can
supply; wiring them in is a mechanical repeat of `_sync_accounts`'s
pattern once that owning phase's client exists, tracked as a follow-up
rather than guessed here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

from iam_sentinel_agents.contracts.memory import SemanticEntity
from iam_sentinel_agents.tools.memory.remember import upsert_semantic, WriterRole

if TYPE_CHECKING:
    from iam_sentinel_adapters.memory.client import MemoryClient
    from mypy_boto3_organizations.client import OrganizationsClient
    from mypy_boto3_sso_admin.client import SSOAdminClient

_WRITER_ROLE: WriterRole = "semantic_syncer"


class SyncSummary(dict[str, int]):
    """Plain-dict subclass so it JSON-serializes as-is for the Lambda
    return value while still supporting attribute-free `summary["changed"]`
    access in tests.
    """


def _body_sha256(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _existing_sha256(memory: MemoryClient, entity_kind: str, entity_key: str) -> str | None:
    existing = memory.recall_semantic(entity_kind, {"entity_key": entity_key})
    if not existing:
        return None
    sha = existing[0].get("body_sha256")
    return sha if isinstance(sha, str) else None


def _sync_one(
    memory: MemoryClient,
    *,
    entity_kind: Any,
    entity_key: str,
    body: dict[str, Any],
    source_of_truth: str,
    related_entities: list[str],
    synced_at: datetime,
    emit_changed: Any,
) -> bool:
    """Writes one entity iff its body changed. Returns whether it changed."""
    new_sha256 = _body_sha256(body)
    if _existing_sha256(memory, entity_kind, entity_key) == new_sha256:
        return False

    entity = SemanticEntity(
        entity_kind=entity_kind,
        entity_key=entity_key,
        body=body,
        synced_at=synced_at,
        source_of_truth=source_of_truth,
        related_entities=related_entities,
        body_sha256=new_sha256,
    )
    upsert_semantic(memory, entity, writer_role=_WRITER_ROLE)
    emit_changed(entity_kind, entity_key)
    return True


def sync_accounts(
    memory: MemoryClient,
    org_client: OrganizationsClient,
    *,
    synced_at: datetime | None = None,
    emit_changed: Any = lambda *_: None,
) -> SyncSummary:
    """`organizations:ListAccounts` -- one `SemanticEntity` per account."""
    when = synced_at or datetime.now(UTC)
    summary = SyncSummary(scanned=0, changed=0)
    for page in org_client.get_paginator("list_accounts").paginate():
        for account in page["Accounts"]:
            summary["scanned"] += 1
            body = {
                "id": account["Id"],
                "name": account["Name"],
                "email": account["Email"],
                "status": account["Status"],
                "joined_method": account.get("JoinedMethod"),
            }
            if _sync_one(
                memory,
                entity_kind="account",
                entity_key=account["Id"],
                body=body,
                source_of_truth="organizations:ListAccounts",
                related_entities=[],
                synced_at=when,
                emit_changed=emit_changed,
            ):
                summary["changed"] += 1
    return summary


def sync_permission_sets(
    memory: MemoryClient,
    sso_client: SSOAdminClient,
    *,
    instance_arn: str,
    synced_at: datetime | None = None,
    emit_changed: Any = lambda *_: None,
) -> SyncSummary:
    """`sso-admin:ListPermissionSets` + `DescribePermissionSet` -- one
    `SemanticEntity` per permission set.
    """
    when = synced_at or datetime.now(UTC)
    summary = SyncSummary(scanned=0, changed=0)
    for page in sso_client.get_paginator("list_permission_sets").paginate(InstanceArn=instance_arn):
        for arn in page["PermissionSets"]:
            summary["scanned"] += 1
            described = sso_client.describe_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=arn
            )["PermissionSet"]
            body = {
                "arn": arn,
                "name": described["Name"],
                "description": described.get("Description"),
                "session_duration": described.get("SessionDuration"),
            }
            if _sync_one(
                memory,
                entity_kind="permission_set",
                entity_key=arn,
                body=body,
                source_of_truth="sso-admin:DescribePermissionSet",
                related_entities=[],
                synced_at=when,
                emit_changed=emit_changed,
            ):
                summary["changed"] += 1
    return summary


def run_syncer(
    memory: MemoryClient,
    *,
    org_client: OrganizationsClient | None,
    sso_client: SSOAdminClient | None = None,
    sso_instance_arn: str | None = None,
    emit_changed: Any = lambda *_: None,
) -> SyncSummary:
    """Orchestrates every wired-in sub-syncer. Idempotent and safe to
    over-invoke (phase-14 §5 Step4) -- a repeat run with unchanged AWS
    state writes nothing and emits nothing.
    """
    total = SyncSummary(scanned=0, changed=0)
    when = datetime.now(UTC)
    if org_client is not None:
        accounts = sync_accounts(memory, org_client, synced_at=when, emit_changed=emit_changed)
        total["scanned"] += accounts["scanned"]
        total["changed"] += accounts["changed"]
    if sso_client is not None and sso_instance_arn is not None:
        permission_sets = sync_permission_sets(
            memory, sso_client, instance_arn=sso_instance_arn, synced_at=when, emit_changed=emit_changed
        )
        total["scanned"] += permission_sets["scanned"]
        total["changed"] += permission_sets["changed"]
    return total


def _emit_entity_changed(events_client: Any, *, entity_kind: str, entity_key: str) -> None:
    events_client.put_events(
        Entries=[
            {
                "Source": "iam-sentinel.memory",
                "DetailType": "EntityChanged",
                "Detail": json.dumps({"entity_kind": entity_kind, "entity_key": entity_key}),
            }
        ]
    )


def memory_semantic_syncer(_event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """EventBridge `rate(1 hour)` entrypoint. Builds its own boto3 clients
    at invoke time (same one-off-client convention as `tools/f5/dispatch.
    py`'s `session_kill_dispatch`, since no adapters-level Organizations/
    SSO-admin/EventBridge client exists yet).
    """
    import boto3
    from iam_sentinel_adapters.memory.client import MemoryClient

    from iam_sentinel_agents.settings import settings

    org_client = boto3.client("organizations", region_name=settings.region)
    events_client = boto3.client("events", region_name=settings.region)
    memory = MemoryClient()

    def emit_changed(entity_kind: str, entity_key: str) -> None:
        _emit_entity_changed(events_client, entity_kind=entity_kind, entity_key=entity_key)

    summary = run_syncer(memory, org_client=org_client, emit_changed=emit_changed)
    return dict(summary)
