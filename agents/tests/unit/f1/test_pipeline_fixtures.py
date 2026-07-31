"""Full scan -> graph -> payload pipeline against the four golden fixtures
(phase-02 §8, §9 acceptance: "wildcard resolver correctness verified on all
four fixtures").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.contracts.passrole import BlastPath, PassRoleEdge
from iam_sentinel_agents.tools.f1 import graph, scan
from tests.unit.f1._provision import load_fixture, provision

pytestmark = pytest.mark.unit

ACCOUNT_ID = "123456789012"
FIXTURE_NAMES = ("admin_shortcut", "service_scoped", "wildcard_pattern", "no_passrole")


@dataclass
class _PipelineResult:
    fixture: dict[str, Any]
    edges: list[PassRoleEdge]
    graph_result: dict[str, Any]


def _run_pipeline(fixture_name: str) -> _PipelineResult:
    fixture = load_fixture(fixture_name)
    iam = boto3.client("iam", region_name="us-east-1")
    provision(iam, fixture)
    session = boto3.Session(region_name="us-east-1")

    scan_result = scan.scan_account(
        ACCOUNT_ID,
        None,
        feature_id="F1",
        correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3",
        session=session,
    )
    edges = [PassRoleEdge.model_validate(raw) for raw in scan_result["edges"]]
    graph_result = graph.build_blast_paths(edges, iam_client=iam)
    return _PipelineResult(fixture=fixture, edges=edges, graph_result=graph_result)


@mock_aws
@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_edge_count_matches_fixture_expectation(fixture_name: str) -> None:
    result = _run_pipeline(fixture_name)
    assert len(result.edges) == result.fixture["expected_edge_count"]


@mock_aws
def test_wildcard_pattern_resolves_exactly_four_prod_roles() -> None:
    result = _run_pipeline("wildcard_pattern")
    assert len(result.edges) == 1
    resolved = result.edges[0].resolved_role_arns
    assert len(resolved) == result.fixture["expected_resolved_role_count"]
    assert all(arn.endswith(("prod-web", "prod-api", "prod-db", "prod-worker")) for arn in resolved)


def _paths_for(result: _PipelineResult, principal_arn: str) -> list[BlastPath]:
    paths: list[BlastPath] = result.graph_result["paths_by_principal"][principal_arn]
    return paths


@mock_aws
def test_admin_shortcut_reaches_critical() -> None:
    result = _run_pipeline("admin_shortcut")
    principal_arn = f"arn:aws:iam::{ACCOUNT_ID}:user/Deployer"
    payload = graph.build_blast_payload(
        account_id=ACCOUNT_ID,
        principal_arn=principal_arn,
        edges=result.edges,
        paths=_paths_for(result, principal_arn),
        graph_stats=result.graph_result["graph_stats"],
    )
    assert payload.blast_score == "CRITICAL"
    assert principal_arn in result.graph_result["critical_principals"]


@mock_aws
def test_service_scoped_reaches_medium_despite_condition() -> None:
    result = _run_pipeline("service_scoped")
    principal_arn = f"arn:aws:iam::{ACCOUNT_ID}:user/PipelineDeployer"
    payload = graph.build_blast_payload(
        account_id=ACCOUNT_ID,
        principal_arn=principal_arn,
        edges=result.edges,
        paths=_paths_for(result, principal_arn),
        graph_stats={},
    )
    assert payload.blast_score == "MEDIUM"
    assert principal_arn not in result.graph_result["critical_principals"]


@mock_aws
def test_wildcard_pattern_stays_low() -> None:
    result = _run_pipeline("wildcard_pattern")
    principal_arn = f"arn:aws:iam::{ACCOUNT_ID}:user/ReleaseEngineer"
    payload = graph.build_blast_payload(
        account_id=ACCOUNT_ID,
        principal_arn=principal_arn,
        edges=result.edges,
        paths=_paths_for(result, principal_arn),
        graph_stats={},
    )
    assert payload.blast_score == "LOW"


@mock_aws
def test_no_passrole_has_empty_edges_and_empty_paths() -> None:
    result = _run_pipeline("no_passrole")
    assert result.edges == []
    assert result.graph_result["paths_by_principal"] == {}
    assert result.graph_result["critical_principals"] == []
