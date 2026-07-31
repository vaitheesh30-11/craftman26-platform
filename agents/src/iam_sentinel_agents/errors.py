"""Exception hierarchy for the agents module's own runtime primitives.

Domain exceptions raised by adapters/ (once that module lands) are distinct
and imported separately; these are the exceptions the shared Lambda runtime
and event parser raise before any adapter is ever reached.
"""

from __future__ import annotations


class SentinelAgentError(Exception):
    """Base for every agents-module runtime exception."""


class ContractError(ValueError, SentinelAgentError):
    """Raised when an inbound Bedrock envelope fails to parse or validate.

    Subclasses ValueError so it composes with Pydantic's own validation
    errors when a handler wraps parsing in a broader try/except ValueError.
    """


class CrossAccountAssumeError(SentinelAgentError):
    """Raised when STS AssumeRole fails after exhausting retries."""

    def __init__(self, account_id: str, role_name: str, *, cause: Exception) -> None:
        super().__init__(f"failed to assume {role_name} in account {account_id}: {cause}")
        self.account_id = account_id
        self.role_name = role_name
        self.__cause__ = cause


class MemoryIsolationError(SentinelAgentError):
    """Raised when a caller attempts to recall/remember episodic memory for
    a `principal` other than the one invoking the turn (phase-14 §3.5:
    "Cross-org contamination is structurally impossible" -- the equivalent
    cross-*principal* invariant for episodic memory is enforced here, at
    the one chokepoint every episodic read/write passes through).
    """

    def __init__(self, invoking_principal: str, target_principal: str) -> None:
        super().__init__(
            f"principal {invoking_principal!r} may not access episodic memory "
            f"scoped to {target_principal!r}"
        )
        self.invoking_principal = invoking_principal
        self.target_principal = target_principal


class MemoryWriteForbiddenError(SentinelAgentError):
    """Raised when a caller other than the designated writer for a memory
    kind attempts `remember` (phase-14 §4: "only Prime's post-turn Lambda
    writes episodic; only the syncer writes semantic; only individual tool
    Lambdas write procedural. Agents cannot write memory directly."). The
    real enforcement boundary is the scoped IAM policy on each Lambda's
    execution role (aws-infra concern, not this module's) -- this exception
    is defense-in-depth at the Python layer for anything that reaches this
    code path despite that.
    """
