"""Real Bedrock calls: `InvokeAgent`, `InvokeAgentWithResponseStream`,
`InvokeModel`, `Retrieve` (phase-01 §3-4).

The adapter never runs its own Guardrail evaluation -- it relies entirely
on the Guardrail Bedrock already applied server-side and only inspects
`stopReason` (phase-01 §8 risk: applying a Guardrail twice).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3

from iam_sentinel_adapters.cost_meter import CostMeter, SpendKind
from iam_sentinel_adapters.errors import GuardrailInterventionError, ThrottlingError
from iam_sentinel_adapters.llm.guardrail import GuardrailAccessor
from iam_sentinel_adapters.llm.model_router import pick_model
from iam_sentinel_adapters.llm.output_validator import validate_output
from iam_sentinel_adapters.llm.types import (
    BedrockAgentResponse,
    BedrockAgentStreamChunk,
    KnowledgeChunk,
)
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic import BaseModel


class BedrockProvider:
    def __init__(
        self,
        *,
        agent_runtime_client: Any = None,
        runtime_client: Any = None,
        cost_meter: CostMeter | None = None,
        guardrail: GuardrailAccessor | None = None,
    ) -> None:
        self._agent_runtime = agent_runtime_client or boto3.client(
            "bedrock-agent-runtime", region_name=settings.region
        )
        self._runtime = runtime_client or boto3.client("bedrock-runtime", region_name=settings.region)
        self._cost_meter = cost_meter or CostMeter()
        self._guardrail = guardrail or GuardrailAccessor()

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
    ) -> BedrockAgentResponse:
        self._cost_meter.check_budget(correlation_id, SpendKind.BEDROCK_AGENT_INVOCATION, 0.10)

        response = self._invoke_agent(
            agentId=agent_id,
            agentAliasId=alias_id,
            sessionId=session_id,
            inputText=input_text,
            enableTrace=enable_trace,
            **({"sessionState": session_state} if session_state else {}),
        )

        completion_chunks: list[str] = []
        trace: dict[str, object] | None = None
        for event in response["completion"]:
            if "chunk" in event:
                completion_chunks.append(event["chunk"]["bytes"].decode("utf-8"))
            if "trace" in event:
                trace = event["trace"]

        completion = "".join(completion_chunks)
        if _is_guardrail_intervened(response):
            raise GuardrailInterventionError(f"guardrail intervened for correlation {correlation_id!r}")

        self._cost_meter.record(correlation_id, SpendKind.BEDROCK_AGENT_INVOCATION, 1.0)
        return BedrockAgentResponse(completion=completion, session_id=session_id, trace=trace)

    def invoke_agent_stream(
        self,
        *,
        agent_id: str,
        alias_id: str,
        session_id: str,
        input_text: str,
        correlation_id: str,
    ) -> Iterator[BedrockAgentStreamChunk]:
        self._cost_meter.check_budget(correlation_id, SpendKind.BEDROCK_AGENT_INVOCATION, 0.10)

        response = self._invoke_agent(
            agentId=agent_id, agentAliasId=alias_id, sessionId=session_id, inputText=input_text
        )

        for event in response["completion"]:
            if "chunk" in event:
                text = event["chunk"]["bytes"].decode("utf-8")
                yield BedrockAgentStreamChunk(text=text, is_final=False)

        self._cost_meter.record(correlation_id, SpendKind.BEDROCK_AGENT_INVOCATION, 1.0)
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

        resolved_model_id = model_id or pick_model(
            request_hint=None, correlation_id=correlation_id, cost_meter=self._cost_meter
        )
        response = self._invoke_model(
            modelId=resolved_model_id,
            messages=messages,
            system=[{"text": system}] if system else [],
            guardrailConfig={
                "guardrailIdentifier": self._guardrail.guardrail_id(),
                "guardrailVersion": self._guardrail.guardrail_version(),
            },
        )

        if response.get("stopReason") == "guardrail_intervened":
            raise GuardrailInterventionError(f"guardrail intervened for correlation {correlation_id!r}")

        usage = response.get("usage", {})
        self._cost_meter.record(correlation_id, SpendKind.BEDROCK_TOKENS, float(usage.get("totalTokens", 0)))

        output_text: str = response["output"]["message"]["content"][0]["text"]
        input_text = "\n".join(m.get("content", "") for m in messages)
        validate_output(output_text, input_text=input_text, sanitized_input_set=set())

        if response_schema is not None:
            parsed: BaseModel = response_schema.model_validate_json(output_text)
            return parsed
        return output_text

    def retrieve(
        self, *, knowledge_base_id: str, query: str, correlation_id: str, top_k: int = 5
    ) -> list[KnowledgeChunk]:
        self._cost_meter.check_budget(correlation_id, SpendKind.ATHENA_SCAN_BYTES, 0.01)

        response = self._retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": top_k}},
        )
        self._cost_meter.record(correlation_id, SpendKind.ATHENA_SCAN_BYTES, 1.0)

        return [
            KnowledgeChunk(
                content=result["content"]["text"],
                source=result.get("location", {}).get("s3Location", {}).get("uri", ""),
                score=result.get("score", 0.0),
                retrieved_on=result.get("metadata", {}).get("retrieved_on"),
            )
            for result in response.get("retrievalResults", [])
        ]

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _invoke_agent(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._agent_runtime.invoke_agent(**kwargs))
        except self._agent_runtime.exceptions.ThrottlingException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._runtime.converse(**kwargs))
        except self._runtime.exceptions.ThrottlingException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _retrieve(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._agent_runtime.retrieve(**kwargs))
        except self._agent_runtime.exceptions.ThrottlingException as exc:
            raise ThrottlingError(str(exc)) from exc


def _is_guardrail_intervened(response: dict[str, Any]) -> bool:
    return bool(response.get("stopReason") == "guardrail_intervened")
