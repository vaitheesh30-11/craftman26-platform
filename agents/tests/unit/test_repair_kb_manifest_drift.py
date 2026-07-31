"""`repair.kb_manifest_drift` (agents phase-17 §7)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.contracts.knowledge_base import QuoteHash
from iam_sentinel_agents.repair.kb_manifest_drift import (
    kb_manifest_drift_repair,
    repair_kb_manifest_drift,
    start_ingestion_for_every_data_source,
)

pytestmark = pytest.mark.unit


def _quote() -> QuoteHash:
    return QuoteHash(
        quote_sha256="a" * 64,
        corpus="iam",
        document="doc-1",
        span_start=0,
        span_end=10,
        retrieved_on="2026-07-31",
    )


def test_start_ingestion_calls_the_bedrock_agent_api_per_data_source() -> None:
    client = MagicMock()
    client.start_ingestion_job.side_effect = [
        {"ingestionJob": {"ingestionJobId": "job-1"}},
        {"ingestionJob": {"ingestionJobId": "job-2"}},
    ]

    job_ids = start_ingestion_for_every_data_source(
        knowledge_base_id="kb-123",
        data_source_ids=["ds-1", "ds-2"],
        bedrock_agent_client=client,
    )

    assert job_ids == ["job-1", "job-2"]
    assert client.start_ingestion_job.call_count == 2
    client.start_ingestion_job.assert_any_call(knowledgeBaseId="kb-123", dataSourceId="ds-1")


def test_repair_kb_manifest_drift_forces_ingestion_and_regenerates_manifest() -> None:
    bedrock_agent_client = MagicMock()
    bedrock_agent_client.start_ingestion_job.return_value = {
        "ingestionJob": {"ingestionJobId": "job-1"}
    }
    manifest_client = MagicMock()
    manifest_client.sign.return_value = "c2ln"
    manifest_client.kms_key_arn = "arn:aws:kms:us-east-1:111111111111:key/abc"
    evidence_client = MagicMock()
    faults_client = MagicMock()

    body = repair_kb_manifest_drift(
        knowledge_base_id="kb-123",
        data_source_ids=["ds-1"],
        quotes_provider=lambda: [_quote()],
        correlation_id="01KBDRIFT",
        bedrock_agent_client=bedrock_agent_client,
        manifest_client=manifest_client,
        evidence_client=evidence_client,
        faults_client=faults_client,
    )

    assert body["ingestion_job_ids"] == ["job-1"]
    assert body["total_quotes"] == 1
    evidence_client.put_signed_evidence.assert_called_once()
    faults_client.put.assert_called_once()
    assert faults_client.put.call_args.args[0]["action_taken"] == "auto_repaired"
    assert faults_client.put.call_args.args[0]["resolved_at"] is not None


def test_kb_manifest_drift_repair_lambda_entrypoint_is_deferred() -> None:
    with pytest.raises(NotImplementedError):
        kb_manifest_drift_repair({}, None)
