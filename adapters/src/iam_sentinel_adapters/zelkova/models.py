"""Result shapes for the Zelkova adapter (phase-02 §2-4).

Mirrors `docs/DATA_CONTRACTS.md` §5 `ZelkovaCheck` in spirit -- `pass_` is
the only field a caller may branch on to decide whether a write is safe --
but this module owns its own dataclasses rather than importing the agents
package's Pydantic model (module-boundary rule: adapters never imports
agents).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

CheckOutcome = Literal["PASS", "FAIL"]


@dataclass(frozen=True)
class Witness:
    """A concrete counter-example Access Analyzer found for a `FAIL` result."""

    principal: str = ""
    action: str = ""
    resource: str = ""
    context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyPair:
    """The existing/candidate policies a check was run against, content-addressed."""

    existing: dict[str, object]
    candidate: dict[str, object]
    existing_sha256: str
    candidate_sha256: str


@dataclass(frozen=True)
class ZelkovaResult:
    """Contract: `pass_ is True` iff Access Analyzer returned `PASS` with no
    exception on the call path. Every error path -- throttle-exhausted,
    `ZelkovaError`, a mismatched post-check -- MUST produce `pass_=False`,
    never raise past this boundary while also claiming a pass (phase-02 §4,
    §8 property test).
    """

    pass_: bool
    result: CheckOutcome
    witness: Witness | None
    latency_ms: int
    invoked_at: datetime
    policy_pair: PolicyPair | None = None
