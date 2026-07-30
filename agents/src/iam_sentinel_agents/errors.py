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
