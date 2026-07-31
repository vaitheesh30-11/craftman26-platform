"""Hand-authored Hypothesis strategies for contract round-trip fuzzing.

Regex-constrained fields (ULIDs, ARNs, account ids, sha256 hex, ISO dates)
are generated directly from a valid alphabet rather than via `st.from_regex`
— per phase-00 risk mitigation, `from_regex` over these patterns is
measurably slower and more prone to shrinking pathologies than a hand-built
strategy constrained to a known-valid alphabet.

Composite strategies (Finding, RemediationPlan) satisfy cross-field
model_validator invariants BY CONSTRUCTION — never via `.filter()` — so
Hypothesis never hits a `filter_too_much` health check regardless of how
narrow an invariant is.
"""

from __future__ import annotations

from datetime import datetime, UTC

from hypothesis import strategies as st

from iam_sentinel_agents.contracts import (
    AwsDocCitation,
    EpisodicMemory,
    EvidenceRef,
    Finding,
    ProceduralHit,
    RecallResult,
    RemediationPlan,
    SemanticEntity,
    ToolInvocation,
    UntrustedContextBlock,
    ZelkovaCheck,
)
from tests.conftest import CANONICAL_QUOTES

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U
_HEX_ALPHABET = "0123456789abcdef"
_ARN_SEGMENT_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"
_BUCKET_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"

FEATURE_IDS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")
SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
VERDICTS = ("CONFIRM", "REJECT", "ESCALATE", "INCONCLUSIVE", "REMEDIATED")
REMEDIATION_ACTIONS = (
    "attach_inline_policy",
    "detach_inline_policy",
    "update_scp",
    "archive_finding",
    "enable_cloudtrail_data_events",
    "auto_generate_policy",
)


def printable_text(min_size: int = 1, max_size: int = 64) -> st.SearchStrategy[str]:
    """ASCII 33..126 — no whitespace at all, so str_strip_whitespace is a no-op."""
    return st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=min_size,
        max_size=max_size,
    )


def ulids() -> st.SearchStrategy[str]:
    return st.text(alphabet=_ULID_ALPHABET, min_size=24, max_size=24).map(lambda s: "01" + s)


def account_ids() -> st.SearchStrategy[str]:
    return st.text(alphabet="0123456789", min_size=12, max_size=12)


def sha256_hexes() -> st.SearchStrategy[str]:
    return st.text(alphabet=_HEX_ALPHABET, min_size=64, max_size=64)


def iso_dates() -> st.SearchStrategy[str]:
    return st.dates(
        min_value=datetime(2020, 1, 1, tzinfo=UTC).date(),
        max_value=datetime(2035, 12, 31, tzinfo=UTC).date(),
    ).map(lambda d: d.isoformat())


def aware_datetimes() -> st.SearchStrategy[datetime]:
    return st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2035, 12, 31),
    ).map(lambda dt: dt.replace(tzinfo=UTC))


def _arn_segment(min_size: int = 1, max_size: int = 12) -> st.SearchStrategy[str]:
    return st.text(alphabet=_ARN_SEGMENT_ALPHABET, min_size=min_size, max_size=max_size)


def iam_role_arns() -> st.SearchStrategy[str]:
    return st.builds(
        lambda account, name: f"arn:aws:iam::{account}:role/{name}",
        account=account_ids(),
        name=_arn_segment(min_size=3, max_size=30),
    )


def kms_key_arns() -> st.SearchStrategy[str]:
    return st.builds(
        lambda region, account, key_id: f"arn:aws:kms:{region}:{account}:key/{key_id}",
        region=st.sampled_from(["us-east-1", "us-west-2", "eu-west-1"]),
        account=account_ids(),
        key_id=st.text(alphabet=_HEX_ALPHABET + "-", min_size=10, max_size=36),
    )


def urls_under_aws_docs() -> st.SearchStrategy[str]:
    return _arn_segment(min_size=1, max_size=20).map(
        lambda seg: f"https://docs.aws.amazon.com/IAM/latest/UserGuide/{seg}.html"
    )


def bucket_names() -> st.SearchStrategy[str]:
    return st.text(alphabet=_BUCKET_ALPHABET, min_size=3, max_size=63)


def canonical_quotes() -> st.SearchStrategy[str]:
    return st.sampled_from(CANONICAL_QUOTES)


def aws_doc_citations() -> st.SearchStrategy[AwsDocCitation]:
    return st.builds(
        AwsDocCitation,
        gap_id=st.sampled_from(FEATURE_IDS),
        quote=canonical_quotes(),
        source=printable_text(1, 60),
        url=urls_under_aws_docs(),
        retrieved_on=iso_dates(),
    )


def evidence_refs() -> st.SearchStrategy[EvidenceRef]:
    return st.builds(
        EvidenceRef,
        bucket=bucket_names(),
        key=printable_text(1, 200),
        version_id=printable_text(1, 50),
        kms_key_arn=kms_key_arns(),
        signature=printable_text(1, 100),
        sha256=sha256_hexes(),
        stored_at=aware_datetimes(),
    )


def zelkova_checks() -> st.SearchStrategy[ZelkovaCheck]:
    return st.builds(
        lambda passed, witness, latency, invoked, base, cand: ZelkovaCheck(
            **{"pass": passed},
            witness=witness,
            latency_ms=latency,
            invoked_at=invoked,
            baseline_hash=base,
            candidate_hash=cand,
        ),
        passed=st.booleans(),
        witness=st.one_of(st.none(), printable_text(1, 100)),
        latency=st.integers(min_value=0, max_value=100_000),
        invoked=aware_datetimes(),
        base=sha256_hexes(),
        cand=sha256_hexes(),
    )


def tool_invocations() -> st.SearchStrategy[ToolInvocation]:
    return st.builds(
        ToolInvocation,
        tool_name=printable_text(1, 50),
        input_hash=sha256_hexes(),
        output_hash=sha256_hexes(),
        duration_ms=st.integers(min_value=0, max_value=900_000),
        zelkova_check=st.none(),
    )


def untrusted_context_blocks() -> st.SearchStrategy[UntrustedContextBlock]:
    return st.builds(
        UntrustedContextBlock,
        type=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=64),
        body=st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), max_size=200),
    )


@st.composite
def findings(draw: st.DrawFn) -> Finding:
    severity = draw(st.sampled_from(SEVERITIES))
    feature_id = draw(st.sampled_from(FEATURE_IDS))
    # CRITICAL requires principal_arn — satisfied by construction, never filtered.
    principal_arn = (
        draw(iam_role_arns())
        if severity == "CRITICAL"
        else draw(st.one_of(st.none(), iam_role_arns()))
    )
    citation = AwsDocCitation(
        gap_id=feature_id,
        quote=draw(canonical_quotes()),
        source=draw(printable_text(1, 50)),
        url=draw(urls_under_aws_docs()),
        retrieved_on=draw(iso_dates()),
    )
    return Finding(
        finding_id=draw(ulids()),
        feature_id=feature_id,
        account_id=draw(account_ids()),
        principal_arn=principal_arn,
        resource_arn=draw(st.one_of(st.none(), iam_role_arns())),
        severity=severity,
        title=draw(printable_text(1, 100)),
        detail=draw(printable_text(1, 500)),
        aws_doc_citation=citation,
        payload={},
        detected_at=draw(aware_datetimes()),
        expires_at=draw(st.one_of(st.none(), aware_datetimes())),
        evidence_ref=None,
    )


@st.composite
def episodic_memories(draw: st.DrawFn) -> EpisodicMemory:
    n_features = draw(st.integers(min_value=1, max_value=8))
    feature_ids = draw(
        st.lists(st.sampled_from(FEATURE_IDS), min_size=n_features, max_size=n_features)
    )
    return EpisodicMemory(
        principal=draw(iam_role_arns()),
        decision_id=draw(ulids()),
        correlation_id=draw(ulids()),
        feature_ids_involved=feature_ids,
        finding_summary=draw(printable_text(1, 200)),
        narrative_excerpt=draw(printable_text(1, 400)),
        evidence_ref=draw(evidence_refs()),
        tags=draw(st.dictionaries(printable_text(1, 20), printable_text(1, 40), max_size=5)),
        decided_at=draw(aware_datetimes()),
    )


def semantic_entities() -> st.SearchStrategy[SemanticEntity]:
    return st.builds(
        SemanticEntity,
        entity_kind=st.sampled_from(
            ["account", "ou", "role", "permission_set", "slr", "policy", "service_principal", "tag"]
        ),
        entity_key=printable_text(1, 100),
        body=st.dictionaries(printable_text(1, 20), printable_text(0, 40), max_size=5),
        synced_at=aware_datetimes(),
        source_of_truth=printable_text(1, 60),
        related_entities=st.lists(printable_text(1, 50), max_size=5),
        body_sha256=sha256_hexes(),
    )


def procedural_hits() -> st.SearchStrategy[ProceduralHit]:
    return st.builds(
        ProceduralHit,
        pattern_kind=printable_text(1, 60),
        pattern_hash=sha256_hexes(),
        result=st.dictionaries(printable_text(1, 20), printable_text(0, 40), max_size=5),
        ttl=st.integers(min_value=1, max_value=86_400 * 30),
        first_computed_at=aware_datetimes(),
        last_hit_at=aware_datetimes(),
        hit_count=st.integers(min_value=1, max_value=10_000),
    )


def recall_results() -> st.SearchStrategy[RecallResult]:
    return st.builds(
        RecallResult,
        kind=st.sampled_from(["episodic", "semantic", "procedural"]),
        hits=st.lists(
            st.dictionaries(printable_text(1, 20), printable_text(0, 40), max_size=5), max_size=10
        ),
        latency_ms=st.integers(min_value=0, max_value=60_000),
        total_scanned=st.integers(min_value=0, max_value=100_000),
    )


@st.composite
def remediation_plans(draw: st.DrawFn) -> RemediationPlan:
    action = draw(st.sampled_from(REMEDIATION_ACTIONS))
    dry_run = draw(st.booleans())
    # dry_run=False requires a PASSING zelkova_pre — satisfied by
    # construction: when dry_run is False we always build a passing check.
    zelkova_pre = None
    if not dry_run:
        zelkova_pre = ZelkovaCheck(
            **{"pass": True},
            witness=None,
            latency_ms=draw(st.integers(min_value=0, max_value=100_000)),
            invoked_at=draw(aware_datetimes()),
            baseline_hash=draw(sha256_hexes()),
            candidate_hash=draw(sha256_hexes()),
        )
    else:
        zelkova_pre = draw(st.one_of(st.none(), zelkova_checks()))
    return RemediationPlan(
        action=action,
        target_arn=draw(iam_role_arns()),
        policy_document={"Version": "2012-10-17", "Statement": []},
        ttl_seconds=draw(st.one_of(st.none(), st.integers(min_value=60, max_value=86_400 * 30))),
        dry_run=dry_run,
        zelkova_pre=zelkova_pre,
        zelkova_post=None,
    )
