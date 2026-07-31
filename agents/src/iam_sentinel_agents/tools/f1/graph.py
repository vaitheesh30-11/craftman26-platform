"""passrole_graph — blast-radius graph over PassRole edges (phase-02 §4
Step 2), built with `networkx.DiGraph` per agents/README.md's reservation
of `networkx` specifically for F1's graphs.

Deliberate deviation from phase-02 §3.2's one-line summary ("pure
computation on the payload; no AWS calls"): that line directly contradicts
Step 2's own requirement two paragraphs later ("For each reached role,
evaluate that role's attached policies for the CRITICAL/HIGH/MEDIUM/LOW
rubric") -- no `PassRoleEdge` field carries the *target* role's own
policies, only the policy that grants the *PassRole* to it. Accurate
CRITICAL/HIGH classification (§9 acceptance: "CRITICAL findings publish to
SNS and reach Security Hub") is unattainable from edge data alone, so this
implementation resolves the contradiction in Step 2's favor: it assumes
into the same account (derived from `edges[0].from_principal`) to fetch
each *reachable* role's own policies, using the identical bounded,
cached, read-only surface `passrole_scan` already uses. See
docs/decisions/0015.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, TYPE_CHECKING

import networkx as nx

from iam_sentinel_agents.contracts.passrole import BlastPath, PassRoleBlastPayload, PassRoleEdge
from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f1.privilege import classify_role_privilege
from iam_sentinel_agents.tools.f1.scan import normalize_policy_document
from iam_sentinel_agents.tools.f1.severity import blast_score

if TYPE_CHECKING:
    import boto3
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_iam.client import IAMClient

    from iam_sentinel_agents.contracts.common import FeatureID
    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

# phase-02 §10 risk mitigation: abort rather than let an org with 10k+
# roles blow up the per-principal BFS.
_MAX_REACHABLE_NODES = 10_000
_MAX_CONCURRENT_POLICY_FETCHES = 10
_DEFAULT_DEPTH = 2


def _account_id_from_arn(arn: str) -> str:
    return arn.split(":")[4]


def _build_graph(edges: list[PassRoleEdge]) -> Any:
    # networkx ships no type stubs; `Any` here (rather than the real
    # `nx.DiGraph` annotation) avoids mypy --strict's no-any-unimported on
    # every caller of this function, per this module's own docstring on
    # why networkx is used unconditionally despite that gap.
    graph = nx.DiGraph()
    for edge in edges:
        graph.add_node(edge.from_principal)
        for target in edge.resolved_role_arns:
            graph.add_edge(edge.from_principal, target)
    return graph


def _statements_from_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    statement = document.get("Statement", [])
    return [statement] if isinstance(statement, dict) else list(statement)


def _role_statements(
    iam: IAMClient, role_name: str, cache: dict[str, dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]]]:
    attached_arns: list[str] = []
    for attached_page in iam.get_paginator("list_attached_role_policies").paginate(
        RoleName=role_name
    ):
        attached_arns.extend(
            attached["PolicyArn"] for attached in attached_page["AttachedPolicies"]
        )

    statements: list[dict[str, Any]] = []
    for policy_arn in attached_arns:
        document = cache.get(policy_arn)
        if document is None:
            policy = iam.get_policy(PolicyArn=policy_arn)["Policy"]
            version = iam.get_policy_version(
                PolicyArn=policy_arn, VersionId=policy["DefaultVersionId"]
            )
            document = normalize_policy_document(version["PolicyVersion"]["Document"])
            cache[policy_arn] = document
        statements.extend(_statements_from_document(document))

    for inline_page in iam.get_paginator("list_role_policies").paginate(RoleName=role_name):
        for policy_name in inline_page["PolicyNames"]:
            inline = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
            statements.extend(
                _statements_from_document(normalize_policy_document(inline["PolicyDocument"]))
            )
    return attached_arns, statements


def classify_reachable_roles(role_arns: set[str], iam: IAMClient) -> dict[str, str]:
    """Classify every reachable role's own privilege level. Roles that no
    longer exist (deleted between scan and graph, or a user-supplied ARN
    that was never real) degrade to "Other" rather than failing the whole
    turn -- a stale edge is a data-quality signal, not a fatal error.
    """
    cache: dict[str, dict[str, Any]] = {}

    def _classify_one(role_arn: str) -> tuple[str, str]:
        role_name = role_arn.rsplit("/", maxsplit=1)[-1]
        try:
            attached_arns, statements = _role_statements(iam, role_name, cache)
        except iam.exceptions.NoSuchEntityException:
            return role_arn, "Other"
        return role_arn, classify_role_privilege(
            attached_policy_arns=attached_arns, statements=statements
        )

    if not role_arns:
        return {}
    with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_POLICY_FETCHES) as pool:
        return dict(pool.map(_classify_one, role_arns))


def build_blast_paths(
    edges: list[PassRoleEdge],
    *,
    depth: int = _DEFAULT_DEPTH,
    iam_client: IAMClient | None = None,
    session: boto3.Session | None = None,
    feature_id: FeatureID = "F1",
    correlation_id: str = "passrole-graph",
) -> dict[str, Any]:
    """Pure over `edges` for graph shape; the *privilege* of each reached
    role still needs a read against that role's own policies (see module
    docstring) -- `iam_client` is the injection point tests use to avoid a
    real `cross_account.assume()` round-trip.
    """
    bounded_depth = min(max(depth, 1), _DEFAULT_DEPTH)
    empty_stats = {"nodes": 0, "edges": len(edges), "depth": bounded_depth, "aborted": 0}
    if not edges:
        return {"paths_by_principal": {}, "critical_principals": [], "graph_stats": empty_stats}

    graph = _build_graph(edges)
    node_count = graph.number_of_nodes()
    aborted = node_count > _MAX_REACHABLE_NODES
    graph_stats = {
        "nodes": node_count,
        "edges": graph.number_of_edges(),
        "depth": bounded_depth,
        "aborted": int(aborted),
    }
    if aborted:
        return {"paths_by_principal": {}, "critical_principals": [], "graph_stats": graph_stats}

    iam = iam_client
    if iam is None:
        account_id = _account_id_from_arn(edges[0].from_principal)
        boto_session = session or cross_account.assume(
            account_id, feature_id=feature_id, correlation_id=correlation_id
        )
        iam = boto_session.client("iam")

    targets = {target for _, target in graph.edges()}
    privileges = classify_reachable_roles(targets, iam)

    paths_by_principal: dict[str, list[BlastPath]] = {}
    critical_principals: list[str] = []
    principals = {edge.from_principal for edge in edges}

    for principal in principals:
        if principal not in graph:
            continue
        lengths = nx.single_source_shortest_path_length(graph, principal, cutoff=bounded_depth)
        blast_paths = [
            BlastPath(
                hops=nx.shortest_path(graph, principal, target),
                reached_privilege=privileges.get(target, "Other"),
                hop_count=hop_count,
            )
            for target, hop_count in lengths.items()
            if hop_count > 0
        ]
        if blast_paths:
            paths_by_principal[principal] = blast_paths
            if any(path.reached_privilege == "AdministratorAccess" for path in blast_paths):
                critical_principals.append(principal)

    return {
        "paths_by_principal": paths_by_principal,
        "critical_principals": critical_principals,
        "graph_stats": graph_stats,
    }


def build_blast_payload(
    *,
    account_id: str,
    principal_arn: str,
    edges: list[PassRoleEdge],
    paths: list[BlastPath],
    graph_stats: dict[str, int],
) -> PassRoleBlastPayload:
    edges_out = [edge for edge in edges if edge.from_principal == principal_arn]
    return PassRoleBlastPayload(
        account_id=account_id,
        principal_arn=principal_arn,
        edges_out=edges_out,
        reachable_paths=paths,
        blast_score=blast_score(paths),
        graph_stats=graph_stats,
    )


@sentinel_handler(feature_id="F1", tool_name="passrole_graph")
def passrole_graph(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    edges = [PassRoleEdge.model_validate(raw) for raw in invocation.parameters.get("edges", [])]
    depth = int(invocation.parameters.get("depth", _DEFAULT_DEPTH))
    result = build_blast_paths(edges, depth=depth, correlation_id=invocation.correlation_id)
    return {
        "paths_by_principal": {
            principal: [path.model_dump(mode="json") for path in paths]
            for principal, paths in result["paths_by_principal"].items()
        },
        "critical_principals": result["critical_principals"],
    }
