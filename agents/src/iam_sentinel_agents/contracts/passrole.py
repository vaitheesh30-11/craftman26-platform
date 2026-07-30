"""PassRoleBlastPayload — F1 PassRole Cartographer's feature payload.

Canonical source: agents/docs/phase-02-passrole-cartographer.txt §3.1. This
is a pure data contract: nothing in `tools/f1/` is required to construct a
`PassRoleBlastPayload` at runtime (the Bedrock Agent itself assembles
`Finding.payload` from the two tools' JSON responses, per the specialist
prompt's REASONING CONTRACT) -- `tools/f1/graph.build_blast_payload` exists
so tests can exercise the whole pipeline against one concrete object
instead of asserting on loose dicts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from iam_sentinel_agents.contracts.common import ACCOUNT_ID_PATTERN, ARN_PATTERN, Base, Severity

ReachedPrivilege = Literal[
    "AdministratorAccess", "PowerUserAccess", "IAMWrite", "SensitiveService", "Other"
]


class PassRoleEdge(Base):
    from_principal: str = Field(pattern=ARN_PATTERN)
    passable_role_pattern: str = Field(min_length=1, max_length=2048)
    resolved_role_arns: list[str] = Field(default_factory=list, max_length=10_000)
    condition_summary: dict[str, str] = Field(default_factory=dict)
    grant_source_policy_arn: str = Field(min_length=1, max_length=2048)
    grant_statement_id: str | None = None


class BlastPath(Base):
    hops: list[str] = Field(min_length=2, max_length=3)
    reached_privilege: ReachedPrivilege
    hop_count: int = Field(ge=1, le=2)


class PassRoleBlastPayload(Base):
    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    principal_arn: str = Field(pattern=ARN_PATTERN)
    edges_out: list[PassRoleEdge] = Field(default_factory=list, max_length=10_000)
    reachable_paths: list[BlastPath] = Field(default_factory=list, max_length=10_000)
    blast_score: Severity
    graph_stats: dict[str, int] = Field(default_factory=dict)
