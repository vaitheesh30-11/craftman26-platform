"""Shared pytest fixtures for the agents module."""

from __future__ import annotations

import hashlib
import unicodedata
from typing import TYPE_CHECKING

import pytest

from iam_sentinel_agents.contracts.finding import set_quote_manifest_provider

if TYPE_CHECKING:
    from collections.abc import Iterator


class _InMemoryManifest:
    def __init__(self, quotes: list[str]) -> None:
        self._hashes = {self._hash(q) for q in quotes}

    @staticmethod
    def _hash(quote: str) -> str:
        normalized = unicodedata.normalize("NFKC", quote)
        collapsed = " ".join(normalized.split())
        return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()

    def contains(self, quote_sha256: str) -> bool:
        return quote_sha256 in self._hashes


CANONICAL_QUOTES: list[str] = [
    "PassRole is not an API call. No CloudTrail logs are generated for iam:PassRole. "
    "The iam:PassRole action is not tracked and is not included in IAM action last "
    "accessed information. It is not included in generated policies.",
    "Custom policy checks are environment-agnostic in their analysis. Their analysis "
    "only considers information contained within the input policies. For example, "
    "custom policy checks cannot check whether an account is a member of a specific "
    "AWS organization. Therefore, the custom policy checks cannot compare new access "
    "based on condition key values for the aws:PrincipalOrgId and aws:PrincipalAccount "
    "condition keys.",
    "Data events not available — IAM Access Analyzer does not identify action-level "
    "activity for data events, such as Amazon S3 data events, in generated policies.",
    "By default, CloudTrail does not log data events such as Amazon S3 object-level "
    "activity (GetObject, DeleteObject).",
    "Test SCPs by creating an organizational unit and moving accounts into it.",
    "Ending an active session for an IAM Identity Center user doesn't end any active "
    "IAM role sessions in the AWS Management Console or AWS CLI.",
    "SCPs have no effect on users or roles in the management account.",
    "SCPs don't apply to the management account — your production workloads have no "
    "SCP guardrails.",
]


@pytest.fixture(autouse=True)
def _install_fixture_manifest() -> Iterator[None]:
    manifest = _InMemoryManifest(CANONICAL_QUOTES)
    set_quote_manifest_provider(lambda: manifest)
    yield
    set_quote_manifest_provider(lambda: None)


@pytest.fixture
def known_quote() -> str:
    return CANONICAL_QUOTES[0]


@pytest.fixture
def unknown_quote() -> str:
    return "This quote is not in any AWS documentation and must be rejected."
