"""`repair.scp_cache_stale` (agents phase-17 §7) -- thin wrapper around
`tools.f6.scp_refresh.refresh_scp_cache` plus the Evidence/Fault
obligations §7's closing line requires.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.repair.scp_cache_stale import (
    repair_scp_cache_stale,
    scp_cache_stale_repair,
)

pytestmark = pytest.mark.unit


def _org_client() -> MagicMock:
    org = MagicMock()
    org.list_roots.return_value = {"Roots": [{"Id": "r-root1"}]}

    def get_paginator(name: str) -> MagicMock:
        if name == "list_organizational_units_for_parent":
            return MagicMock(paginate=lambda **_kw: [{"OrganizationalUnits": []}])
        if name == "list_policies_for_target":
            return MagicMock(paginate=lambda **_kw: [{"Policies": []}])
        raise AssertionError(f"unexpected paginator: {name}")

    org.get_paginator.side_effect = get_paginator
    return org


def test_repair_scp_cache_stale_refreshes_and_emits_evidence_and_fault() -> None:
    org = _org_client()
    policies_client = MagicMock()
    evidence_client = MagicMock()
    faults_client = MagicMock()

    body = repair_scp_cache_stale(
        org_id="o-abc123",
        correlation_id="01SCPSTALE",
        organizations_client=org,
        policies_client=policies_client,
        evidence_client=evidence_client,
        faults_client=faults_client,
    )

    assert body["org_id"] == "o-abc123"
    assert body["levels_cached"] == 1
    evidence_client.put_signed_evidence.assert_called_once()
    assert evidence_client.put_signed_evidence.call_args.kwargs["kind"] == "repair_action"
    faults_client.put.assert_called_once()
    assert faults_client.put.call_args.args[0]["action_taken"] == "auto_repaired"


def test_scp_cache_stale_repair_lambda_entrypoint_reads_org_id_from_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called_with: dict[str, object] = {}

    def _fake_refresh(
        *, org_id: str, organizations_client: object, policies: object
    ) -> dict[str, int]:
        called_with["org_id"] = org_id
        return {"levels_cached": 0, "policies_cached": 0}

    monkeypatch.setattr(
        "iam_sentinel_agents.repair.scp_cache_stale.refresh_scp_cache", _fake_refresh
    )
    monkeypatch.setattr(
        "iam_sentinel_agents.repair.scp_cache_stale.EvidenceClient", lambda: MagicMock()
    )
    monkeypatch.setattr("iam_sentinel_agents.tools.common.retry.FaultsClient", lambda: MagicMock())

    scp_cache_stale_repair({"org_id": "o-fromevent"}, None)

    assert called_with["org_id"] == "o-fromevent"
