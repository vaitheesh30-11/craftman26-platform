"""The Finding citation validator must reject invented quotes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from iam_sentinel_agents.contracts import AwsDocCitation
from iam_sentinel_agents.contracts.finding import _canonical_quote_hash
from tests.contract._factories import make_finding

pytestmark = pytest.mark.contract


def test_known_quote_accepted(known_quote: str) -> None:
    citation = AwsDocCitation(
        gap_id="F1",
        quote=known_quote,
        source="AWS IAM User Guide",
        url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html",
        retrieved_on="2026-07-30",
    )
    assert citation.quote_sha256 == _canonical_quote_hash(known_quote)


def test_unknown_quote_rejected(unknown_quote: str) -> None:
    with pytest.raises(ValidationError, match="not found in KB manifest"):
        AwsDocCitation(
            gap_id="F1",
            quote=unknown_quote,
            source="AWS IAM User Guide",
            url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html",
            retrieved_on="2026-07-30",
        )


def test_quote_hash_stable_across_whitespace_variants(known_quote: str) -> None:
    """The manifest hash canonicalizes whitespace; extra spaces still match."""
    citation_a = AwsDocCitation(
        gap_id="F1",
        quote=known_quote,
        source="AWS IAM User Guide",
        url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html",
        retrieved_on="2026-07-30",
    )
    citation_b = AwsDocCitation(
        gap_id="F1",
        quote=known_quote.replace(" ", "  ").replace(".", ".\n"),
        source="AWS IAM User Guide",
        url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html",
        retrieved_on="2026-07-30",
    )
    assert citation_a.quote_sha256 == citation_b.quote_sha256


def test_critical_finding_requires_principal() -> None:
    with pytest.raises(ValidationError, match="requires principal_arn"):
        make_finding(principal_arn=None)


def test_finding_carries_valid_citation() -> None:
    finding = make_finding()
    assert finding.aws_doc_citation.gap_id == "F1"
    assert finding.aws_doc_citation.url.startswith("https://docs.aws.amazon.com/")
