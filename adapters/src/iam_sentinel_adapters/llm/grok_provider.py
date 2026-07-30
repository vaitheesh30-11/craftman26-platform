"""Local-dev LLM provider: xAI's OpenAI-compatible chat-completions
endpoint standing in for Bedrock Agents (`SENTINEL_LLM_PROVIDER=grok`,
docs/EXECUTION_PLAN.txt §2; see ADR 0007).

Multi-agent collaboration is emulated in-process -- `invoke_agent` makes
one direct chat-completion call framed as the named agent, with no real
Supervisor→Collaborator hop. Guardrail intervention is emulated by the
sanitizer's forbidden-pattern list rather than a real Bedrock Guardrail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import requests

from iam_sentinel_adapters.cost_meter import CostMeter, SpendKind
from iam_sentinel_adapters.errors import GuardrailInterventionError, ThrottlingError
from iam_sentinel_adapters.llm.output_validator import validate_output
from iam_sentinel_adapters.llm.types import (
    BedrockAgentResponse,
    BedrockAgentStreamChunk,
    KnowledgeChunk,
)
from iam_sentinel_adapters.prompts.sanitizer import FORBIDDEN_PATTERNS
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic import BaseModel

_XAI_CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"
_REQUEST_TIMEOUT_SECONDS = 30
_HTTP_TOO_MANY_REQUESTS = 429


class GrokProvider:
    def __init__(
        self, *, session: requests.Session | None = None, cost_meter: CostMeter | None = None
    ) -> None:
        self._session = session or requests.Session()
        self._cost_meter = cost_meter or CostMeter()

    def invoke_agent(
        self,
        *,
        agent_id: str,
        alias_id: str,
        session_id: str,
        input_text: str,
        correlation_id: str,
        session_state: dict[str, object] | None = None,  # noqa: ARG002 -- no real multi-agent hop to carry state
        enable_trace: bool = False,  # noqa: ARG002 -- no real trace to emit
    ) -> BedrockAgentResponse:
        self._cost_meter.check_budget(correlation_id, SpendKind.BEDROCK_AGENT_INVOCATION, 0.10)
        completion = self._chat_completion(
            messages=[
                {"role": "system", "content": f"You are Bedrock agent {agent_id!r}, alias {alias_id!r}."},
                {"role": "user", "content": input_text},
            ],
            correlation_id=correlation_id,
        )
        self._structural_guardrail(completion)
        return BedrockAgentResponse(completion=completion, session_id=session_id)

    def invoke_agent_stream(
        self,
        *,
        agent_id: str,
        alias_id: str,
        session_id: str,
        input_text: str,
        correlation_id: str,
    ) -> Iterator[BedrockAgentStreamChunk]:
        response = self.invoke_agent(
            agent_id=agent_id,
            alias_id=alias_id,
            session_id=session_id,
            input_text=input_text,
            correlation_id=correlation_id,
        )
        yield BedrockAgentStreamChunk(text=response.completion, is_final=False)
        yield BedrockAgentStreamChunk(text="", is_final=True)

    def invoke_model(
        self,
        *,
        model_id: str | None = None,
        messages: list[dict[str, str]],
        correlation_id: str,
        system: str | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> BaseModel | str:
        self._cost_meter.check_budget(correlation_id, SpendKind.BEDROCK_TOKENS, 0.05)
        full_messages = ([{"role": "system", "content": system}] if system else []) + messages
        output_text = self._chat_completion(
            messages=full_messages, correlation_id=correlation_id, model_id=model_id
        )
        self._structural_guardrail(output_text)

        input_text = "\n".join(m.get("content", "") for m in messages)
        validate_output(output_text, input_text=input_text, sanitized_input_set=set())

        if response_schema is not None:
            return response_schema.model_validate_json(output_text)
        return output_text

    def retrieve(
        self, *, knowledge_base_id: str, query: str, correlation_id: str, top_k: int = 5  # noqa: ARG002
    ) -> list[KnowledgeChunk]:
        # Local dev has no Bedrock KB, and Grok mode has no vector store of
        # its own to substitute (KB ingestion is agents phase-10). An empty
        # result here is the expected degraded behavior, not a failure.
        self._cost_meter.check_budget(correlation_id, SpendKind.ATHENA_SCAN_BYTES, 0.01)
        return []

    def _structural_guardrail(self, text: str) -> None:
        for name, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                raise GuardrailInterventionError(f"local structural guardrail matched {name!r}")

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _chat_completion(
        self, *, messages: list[dict[str, str]], correlation_id: str, model_id: str | None = None
    ) -> str:
        response = self._session.post(
            _XAI_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {settings.xai_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model_id or settings.grok_model_id, "messages": messages},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == _HTTP_TOO_MANY_REQUESTS:
            raise ThrottlingError(f"xAI throttled correlation {correlation_id!r}")
        response.raise_for_status()

        body: dict[str, Any] = response.json()
        usage = body.get("usage", {})
        self._cost_meter.record(
            correlation_id, SpendKind.BEDROCK_TOKENS, float(usage.get("total_tokens", 0))
        )
        return str(body["choices"][0]["message"]["content"])
