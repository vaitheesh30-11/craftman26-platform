from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock

from iam_sentinel_adapters.evidence.client import EvidenceRef

from iam_sentinel_agents.prime.post_turn import PrimePostTurnProcessor
from tests.contract._factories import make_finding, make_query, make_verdict


def _fake_evidence_ref() -> EvidenceRef:
    return EvidenceRef(
        bucket="sentinel-evidence-dev",
        key="F1/2026/07/31/corr/specialist_output/abc.json",
        version_id="v1",
        kms_key_arn="arn:aws:kms:us-east-1:111122223333:key/mrk-a1b2c3d4e5f6789012345678901234ab",
        signature="sig==",
        sha256="a" * 64,
        stored_at=datetime.now(UTC),
    )


def _build_processor() -> tuple[PrimePostTurnProcessor, dict[str, MagicMock]]:
    mocks = {
        "idempotency": MagicMock(),
        "decisions": MagicMock(),
        "evidence": MagicMock(),
        "security_hub": MagicMock(),
        "sns": MagicMock(),
    }
    mocks["idempotency"].claim.return_value = True
    mocks["evidence"].put_signed_evidence.return_value = _fake_evidence_ref()
    processor = PrimePostTurnProcessor(
        idempotency=mocks["idempotency"],
        decisions=mocks["decisions"],
        evidence=mocks["evidence"],
        security_hub=mocks["security_hub"],
        sns=mocks["sns"],
    )
    return processor, mocks


def test_process_writes_decision_and_evidence_for_a_clean_confirm() -> None:
    processor, mocks = _build_processor()
    query = make_query()
    verdicts = [make_verdict(verdict="CONFIRM", findings=[])]

    decision = processor.process(query=query, verdicts=verdicts, narrative="all clear")

    assert decision is not None
    assert decision.status == "ANSWERED"
    mocks["decisions"].put.assert_called_once()
    mocks["evidence"].put_signed_evidence.assert_called_once()
    mocks["sns"].publish_critical_finding.assert_not_called()
    mocks["security_hub"].import_findings.assert_not_called()


def test_process_escalates_to_sns_and_security_hub_on_critical_finding() -> None:
    processor, mocks = _build_processor()
    query = make_query()
    verdicts = [make_verdict(verdict="CONFIRM", findings=[make_finding(severity="CRITICAL")])]

    decision = processor.process(query=query, verdicts=verdicts, narrative="critical exposure found")

    assert decision is not None
    mocks["sns"].publish_critical_finding.assert_called_once()
    mocks["security_hub"].import_findings.assert_called_once()


def test_process_skips_side_effects_on_idempotent_replay() -> None:
    processor, mocks = _build_processor()
    mocks["idempotency"].claim.return_value = False
    query = make_query()
    verdicts = [make_verdict(verdict="CONFIRM")]

    decision = processor.process(query=query, verdicts=verdicts, narrative="replay")

    assert decision is None
    mocks["decisions"].put.assert_not_called()
    mocks["evidence"].put_signed_evidence.assert_not_called()
