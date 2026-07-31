"""ScpCollisionPayload -- F7 Collision Resolver's feature payload.

Canonical source: agents/docs/phase-08-collision-resolver.txt §3. Pure data
contract, same shape of role as `contracts/passrole.py` for F1
(docs/DATA_CONTRACTS.md §8 index entry): `tools/f7/collision.build_payload`
exists so tests exercise one concrete object instead of asserting on loose
dicts, but nothing in `tools/f7/` requires constructing a `ScpCollisionPayload`
at runtime -- the Bedrock Agent assembles `Finding.payload` from the
`collision_resolve` tool's JSON response per the specialist prompt's
REASONING CONTRACT.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from iam_sentinel_agents.contracts.common import ACCOUNT_ID_PATTERN, Base

ScpLevel = Literal["root", "ou", "account"]


class ScpCollision(Base):
    action_pattern: str = Field(min_length=1, max_length=256)
    resource_pattern: str = Field(min_length=1, max_length=2048)
    allowed_by_scp_arn: str | None = Field(default=None, max_length=2048)
    allowed_at_level: ScpLevel | None = None
    denied_by_scp_arn: str = Field(min_length=1, max_length=2048)
    denied_at_level: ScpLevel
    denying_statement_id: str | None = Field(default=None, max_length=256)
    plain_english: str = Field(min_length=1, max_length=4096)
    minimal_fix: dict[str, object] = Field(default_factory=dict)


class ScpCollisionPayload(Base):
    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    scp_chain: list[dict[str, object]] = Field(default_factory=list, max_length=64)
    effective_policy: dict[str, object] = Field(default_factory=dict)
    collision_count: int = Field(ge=0)
    collisions: list[ScpCollision] = Field(default_factory=list, max_length=10_000)
    engine_version: str = Field(min_length=1, max_length=32)


__all__ = ["ScpCollision", "ScpCollisionPayload", "ScpLevel"]
