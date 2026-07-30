"""Shared response shapes and the provider Protocol both `BedrockProvider`
and `GrokProvider` implement (phase-01 §3; docs/EXECUTION_PLAN.txt §2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic import BaseModel


@dataclass(frozen=True)
class BedrockAgentResponse:
    completion: str
    session_id: str
    trace: dict[str, object] | None = None
    citations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BedrockAgentStreamChunk:
    text: str
    is_final: bool
    guardrail_intervened: bool = False


@dataclass(frozen=True)
class KnowledgeChunk:
    content: str
    source: str
    score: float


class LLMProvider(Protocol):
    def invoke_agent(
        self,
        *,
        agent_id: str,
        alias_id: str,
        session_id: str,
        input_text: str,
        correlation_id: str,
        session_state: dict[str, object] | None = None,
        enable_trace: bool = False,
    ) -> BedrockAgentResponse: ...

    def invoke_agent_stream(
        self,
        *,
        agent_id: str,
        alias_id: str,
        session_id: str,
        input_text: str,
        correlation_id: str,
    ) -> Iterator[BedrockAgentStreamChunk]: ...

    def invoke_model(
        self,
        *,
        model_id: str,
        messages: list[dict[str, str]],
        correlation_id: str,
        system: str | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> BaseModel | str: ...

    def retrieve(
        self, *, knowledge_base_id: str, query: str, correlation_id: str, top_k: int = 5
    ) -> list[KnowledgeChunk]: ...
