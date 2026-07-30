"""retrieve_grounded_chunks passes through the adapter's LLMProvider.retrieve
and emits the staleness metric per chunk (agents phase-10 §4 steps 4, 6)."""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock

from iam_sentinel_adapters.llm.types import KnowledgeChunk

from iam_sentinel_agents.knowledge_base.retrieval import retrieve_grounded_chunks

_TODAY = datetime.now(UTC).date()
_FRESH_DATE = (_TODAY - timedelta(days=1)).isoformat()
_STALE_DATE = (_TODAY - timedelta(days=60)).isoformat()


def test_stale_chunk_emits_metric_fresh_chunk_does_not() -> None:
    provider = MagicMock()
    provider.retrieve.return_value = [
        KnowledgeChunk(content="fresh", source="s3://a", score=0.9, retrieved_on=_FRESH_DATE),
        KnowledgeChunk(content="stale", source="s3://b", score=0.8, retrieved_on=_STALE_DATE),
    ]
    metrics = MagicMock()

    chunks = retrieve_grounded_chunks(
        provider,
        query="q",
        correlation_id="corr-1",
        feature_id="F1",
        metrics=metrics,
        knowledge_base_id="kb-1",
    )

    assert len(chunks) == 2
    metrics.add_metric.assert_called_once()
    assert metrics.add_metric.call_args.kwargs["name"] == "SentinelKbStaleRetrieval"


def test_missing_retrieved_on_is_never_flagged_stale() -> None:
    provider = MagicMock()
    provider.retrieve.return_value = [
        KnowledgeChunk(content="unknown-age", source="s3://c", score=0.7, retrieved_on=None)
    ]
    metrics = MagicMock()

    retrieve_grounded_chunks(
        provider,
        query="q",
        correlation_id="corr-2",
        feature_id="F1",
        metrics=metrics,
        knowledge_base_id="kb-1",
    )

    metrics.add_metric.assert_not_called()
