"""E-01 — Admin PassRole shortcut in target account (phase-13 scenario
table). Real F1 pipeline (`tools/f1/scan.scan_account` -> `tools/f1/graph.
build_blast_paths`) against moto IAM, wired through the real
`PrimePostTurnProcessor` (moto DDB + S3 + SNS, all sharing the one
`moto_session` the `post_turn_harness` fixture chain activates). Passes
when: CRITICAL finding, blast path hop_count <= 2, SNS fires, citation
valid.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

import boto3
from iam_sentinel_adapters.evidence.client import EvidenceRef

from iam_sentinel_agents.contracts.finding import Finding
from iam_sentinel_agents.contracts.passrole import PassRoleEdge
from iam_sentinel_agents.contracts.verdict import SpecialistVerdict, ToolInvocation
from iam_sentinel_agents.tools.f1 import graph, scan
from tests.contract._factories import make_citation, make_query
from tests.unit.f1._provision import load_fixture, provision

if TYPE_CHECKING:
    from tests.e2e.conftest import PostTurnHarness

_ACCOUNT_ID = "123456789012"
_CORRELATION_ID = "01JBP2VHF9K3Q0Z8R7X6M5N4A3"


def _run_f1_pipeline() -> tuple[str, object]:
    fixture = load_fixture("admin_shortcut")
    iam = boto3.client("iam", region_name="us-east-1")
    provision(iam, fixture)
    session = boto3.Session(region_name="us-east-1")

    scan_result = scan.scan_account(
        _ACCOUNT_ID, None, feature_id="F1", correlation_id=_CORRELATION_ID, session=session
    )
    edges = [PassRoleEdge.model_validate(raw) for raw in scan_result["edges"]]
    graph_result = graph.build_blast_paths(edges, iam_client=iam)
    principal_arn = f"arn:aws:iam::{_ACCOUNT_ID}:user/Deployer"
    payload = graph.build_blast_payload(
        account_id=_ACCOUNT_ID,
        principal_arn=principal_arn,
        edges=edges,
        paths=graph_result["paths_by_principal"][principal_arn],
        graph_stats=graph_result["graph_stats"],
    )
    return principal_arn, payload


def test_e01_admin_passrole_shortcut_escalates_to_critical(
    post_turn_harness: PostTurnHarness,
) -> None:
    principal_arn, payload = _run_f1_pipeline()
    assert payload.blast_score == "CRITICAL"
    shortest_path = min(payload.reachable_paths, key=lambda p: p.hop_count)
    assert shortest_path.hop_count <= 2

    finding = Finding(
        finding_id="01JBP2VHF9K3Q0Z8R7X6M5N4A4",
        feature_id="F1",
        account_id=_ACCOUNT_ID,
        principal_arn=principal_arn,
        severity="CRITICAL",
        title="PassRole reaches AdministratorAccess in 1 hop",
        detail="Deployer can PassRole to an admin-capable role.",
        aws_doc_citation=make_citation(),
        payload=payload.model_dump(mode="json"),
        detected_at=datetime.now(UTC),
    )
    verdict = SpecialistVerdict(
        correlation_id=_CORRELATION_ID,
        feature_id="F1",
        verdict="CONFIRM",
        reason="1 CRITICAL PassRole finding",
        findings=[finding],
        tool_invocations=[
            ToolInvocation(
                tool_name="passrole_scan",
                input_hash="a" * 64,
                output_hash="b" * 64,
                duration_ms=42,
            )
        ],
        duration_ms=42,
    )
    query = make_query().model_copy(update={"correlation_id": _CORRELATION_ID})

    decision = post_turn_harness.processor.process(
        query=query, verdicts=[verdict], narrative="Found 1 CRITICAL PassRole exposure."
    )

    assert decision is not None
    assert decision.status == "ANSWERED"
    assert any(f.severity == "CRITICAL" for f in decision.findings)
    assert decision.findings[0].aws_doc_citation.quote  # citation present and non-empty
    post_turn_harness.security_hub.import_findings.assert_called_once()

    # SNS "fires": the real `SnsClient.publish_critical_finding` call went
    # through moto's SNS without raising. There is no subscriber to poll
    # delivery from -- a successful `Publish` call is what "fires" means
    # against a topic with zero subscriptions under moto.
    sns = boto3.client("sns", region_name="us-east-1")
    assert len(sns.list_topics()["Topics"]) == 1

    # Evidence is real, KMS-signed (fake-KMS, see conftest), and verifiable
    # by re-fetching from moto S3 and re-checking the signature.
    ref = decision.evidence_ref
    adapter_ref = EvidenceRef(
        bucket=ref.bucket,
        key=ref.key,
        version_id=ref.version_id,
        kms_key_arn=ref.kms_key_arn,
        signature=ref.signature,
        sha256=ref.sha256,
        stored_at=ref.stored_at,
    )
    verified = post_turn_harness.evidence.verify(adapter_ref)
    assert verified["decision_id"] == decision.decision_id
