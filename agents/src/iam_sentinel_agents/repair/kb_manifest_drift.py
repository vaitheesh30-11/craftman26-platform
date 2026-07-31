"""repair/kb_manifest_drift -- §7's second repair Lambda.

"Trigger: SentinelKbStaleRetrieval > 10/hour. Force
bedrock-agent:StartIngestionJob on every KB data source. Regenerate
manifest via phase-10 §Step 2."

`start_ingestion_for_every_data_source` is real, boto3-direct
`bedrock-agent:StartIngestionJob` (no adapter wraps this API yet; same
"boto3 directly, documented exception" precedent `tools/f6/scp_refresh.py`
and `tools/f8/refresh.py` already established for read-mostly AWS surfaces
no adapter covers). Manifest regeneration reuses phase-10's own
`build_and_publish_manifest` verbatim -- but that function's required input
(`list[QuoteHash]`, i.e. the actual corpus) has no producer anywhere in
this repo yet: phase-10's `kb_corpus_fetch`/`kb_manifest_generate` Lambdas
are themselves deferred per ADR 0010 (`EventStack.PENDING_EVENT_BINDINGS`:
`KbCorpusFetchSchedule`, `KbManifestGenerateChain`, both still pending).
`repair_kb_manifest_drift` therefore takes `quotes_provider` as a required
injection point rather than silently fabricating a corpus -- the same
"build against the documented contract, defer the missing upstream
producer" shape as `repair_semantic_entity`'s `resync` parameter above.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

import boto3
from iam_sentinel_adapters.evidence import EvidenceClient

from iam_sentinel_agents.knowledge_base.manifest_service import build_and_publish_manifest
from iam_sentinel_agents.tools.common.retry import record_fault

if TYPE_CHECKING:
    from collections.abc import Callable

    from aws_lambda_powertools.utilities.typing import LambdaContext
    from iam_sentinel_adapters.ddb.faults import FaultsClient
    from iam_sentinel_adapters.knowledge_base.manifest_client import KbManifestClient
    from mypy_boto3_bedrock_agent import AgentsforBedrockClient

    from iam_sentinel_agents.contracts.knowledge_base import KbManifest, QuoteHash


def start_ingestion_for_every_data_source(
    *,
    knowledge_base_id: str,
    data_source_ids: list[str],
    bedrock_agent_client: AgentsforBedrockClient | None = None,
) -> list[str]:
    """Returns the started `ingestionJobId`s, one per data source."""
    client: AgentsforBedrockClient = bedrock_agent_client or boto3.client("bedrock-agent")
    job_ids: list[str] = []
    for data_source_id in data_source_ids:
        response = client.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id
        )
        job_ids.append(str(response["ingestionJob"]["ingestionJobId"]))
    return job_ids


def repair_kb_manifest_drift(
    *,
    knowledge_base_id: str,
    data_source_ids: list[str],
    quotes_provider: Callable[[], list[QuoteHash]],
    correlation_id: str = "repair-kb-manifest-drift",
    bedrock_agent_client: AgentsforBedrockClient | None = None,
    manifest_client: KbManifestClient | None = None,
    evidence_client: EvidenceClient | None = None,
    faults_client: FaultsClient | None = None,
) -> dict[str, Any]:
    job_ids = start_ingestion_for_every_data_source(
        knowledge_base_id=knowledge_base_id,
        data_source_ids=data_source_ids,
        bedrock_agent_client=bedrock_agent_client,
    )
    manifest: KbManifest = build_and_publish_manifest(quotes_provider(), client=manifest_client)

    body = {
        "knowledge_base_id": knowledge_base_id,
        "ingestion_job_ids": job_ids,
        "manifest_sha256": manifest.manifest_sha256,
        "total_quotes": manifest.total_quotes,
    }
    (evidence_client or EvidenceClient()).put_signed_evidence(
        kind="repair_action",
        body=body,
        correlation_id=correlation_id,
        feature_id="F8",
    )
    record_fault(
        correlation_id=correlation_id,
        fault_class="data_corruption",
        origin="repair:kb_manifest_drift",
        action_taken="auto_repaired",
        detail=f"forced re-ingestion of {len(job_ids)} data source(s), regenerated manifest",
        resolved_at=datetime.now(UTC),
        faults_client=faults_client,
        force_write=True,
    )
    return body


def kb_manifest_drift_repair(event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """Alarm-action Lambda entrypoint (§7 trigger: `SentinelKbStaleRetrieval
    > 10/hour`). `quotes_provider` cannot be supplied over a Lambda event
    payload (it is a callable, not JSON) -- deferred until phase-10's
    corpus-fetch pipeline exists to call directly; documented in this
    phase's ADR, not silently stubbed.
    """
    raise NotImplementedError(
        "kb_manifest_drift_repair's Lambda envelope needs phase-10's corpus-fetch "
        "pipeline (ADR 0010) to exist before quotes_provider has a real implementation; "
        "call repair_kb_manifest_drift() directly with an injected quotes_provider until then"
    )
