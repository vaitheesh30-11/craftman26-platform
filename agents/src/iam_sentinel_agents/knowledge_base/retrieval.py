"""RAG entrypoint specialists call to ground a query in `SentinelKB`
(agents phase-10 §4 steps 4 and 6). Wraps `LLMProvider.retrieve()`
(adapters phase-01) with the freshness contract. No specialist consumes
this yet -- Prime and F1 land in Wave 3 -- so it is exercised here only by
unit tests, ready for whichever specialist adopts it first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_agents.knowledge_base.freshness import emit_stale_retrieval_metric, is_stale
from iam_sentinel_agents.settings import settings

if TYPE_CHECKING:
    from aws_lambda_powertools import Metrics
    from iam_sentinel_adapters.llm.types import KnowledgeChunk, LLMProvider


def retrieve_grounded_chunks(
    provider: LLMProvider,
    *,
    query: str,
    correlation_id: str,
    feature_id: str,
    metrics: Metrics,
    knowledge_base_id: str | None = None,
    top_k: int = 5,
) -> list[KnowledgeChunk]:
    resolved_kb_id = knowledge_base_id or settings.kb_knowledge_base_id
    chunks = provider.retrieve(
        knowledge_base_id=resolved_kb_id,
        query=query,
        correlation_id=correlation_id,
        top_k=top_k,
    )
    for chunk in chunks:
        if chunk.retrieved_on is not None and is_stale(chunk.retrieved_on):
            emit_stale_retrieval_metric(metrics, feature_id=feature_id)
    return chunks
