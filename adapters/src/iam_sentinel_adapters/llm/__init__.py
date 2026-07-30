"""LLM adapter: Bedrock in AWS, Grok for local dev, one interface (phase-01;
docs/EXECUTION_PLAN.txt §2)."""

from __future__ import annotations

from iam_sentinel_adapters.llm.bedrock_provider import BedrockProvider
from iam_sentinel_adapters.llm.factory import get_provider
from iam_sentinel_adapters.llm.grok_provider import GrokProvider
from iam_sentinel_adapters.llm.guardrail import GuardrailAccessor
from iam_sentinel_adapters.llm.model_router import pick_model
from iam_sentinel_adapters.llm.output_validator import validate_output
from iam_sentinel_adapters.llm.types import (
    BedrockAgentResponse,
    BedrockAgentStreamChunk,
    KnowledgeChunk,
    LLMProvider,
)

__all__ = [
    "BedrockAgentResponse",
    "BedrockAgentStreamChunk",
    "BedrockProvider",
    "GrokProvider",
    "GuardrailAccessor",
    "KnowledgeChunk",
    "LLMProvider",
    "get_provider",
    "pick_model",
    "validate_output",
]
