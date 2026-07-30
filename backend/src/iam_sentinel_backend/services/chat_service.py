"""`POST /agent/chat` (backend phase-01 §4).

Prime's own specialist fan-out and result synthesis happen inside Bedrock
(SUPERVISOR collaboration, docs/decisions/0013) and its post-turn Lambda
(`agents/src/iam_sentinel_agents/prime/post_turn.py`, already built) --
this service's job per §4 steps 3-6 is narrower than "parse the model's
answer": kick off the turn via `invoke_agent`, then poll `SentinelDecisions`
for the `DecisionRecord` the post-turn Lambda writes out-of-band. That is
also *why* this doesn't import `agents.prime.result_parser`: reconstructing
structured `Finding`/`SpecialistVerdict` objects from Prime's raw
completion text here would duplicate business logic `agents/` already owns
and validates (module boundary, `schemas/__init__.py`) -- the one thing
this endpoint contributes that the post-turn Lambda doesn't is the
bounded wait itself.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

from fastapi import status
from iam_sentinel_adapters.errors import GuardrailInterventionError, SentinelAdapterError
from iam_sentinel_adapters.prompts.sanitizer import sanitize_untrusted

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.schemas.decision import DecisionOut
from iam_sentinel_backend.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.decisions import DecisionsClient
    from iam_sentinel_adapters.llm.types import LLMProvider

    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.schemas.chat import ChatRequest


class ChatService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        decisions_client: DecisionsClient,
        agent_id: str | None = None,
        alias_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._decisions = decisions_client
        self._agent_id = agent_id or settings.prime_agent_id
        self._alias_id = alias_id or settings.prime_agent_alias_id

    async def ask_prime(
        self, *, request: ChatRequest, principal: Principal, correlation_id: str
    ) -> DecisionOut:
        if request.include_streaming:
            raise SentinelHTTPException(
                code="USE_WEBSOCKET_FOR_STREAMING",
                message="include_streaming=true requires the WebSocket endpoint (backend phase-02)",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        sanitized_query_text = sanitize_untrusted(request.query_text)

        try:
            await asyncio.to_thread(
                self._provider.invoke_agent,
                agent_id=self._agent_id,
                alias_id=self._alias_id,
                session_id=correlation_id,
                input_text=sanitized_query_text,
                correlation_id=correlation_id,
                session_state={
                    "sessionAttributes": {"correlation_id": correlation_id},
                    "promptSessionAttributes": {"principal": principal.arn},
                },
                enable_trace=False,
            )
        except GuardrailInterventionError as exc:
            raise SentinelHTTPException(
                code="GUARDRAIL_INTERVENTION",
                message=str(exc),
                http_status=status.HTTP_400_BAD_REQUEST,
            ) from exc
        except SentinelAdapterError as exc:
            raise SentinelHTTPException(
                code="PRIME_INVOCATION_FAILED",
                message=str(exc),
                http_status=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        decision = await self._poll_for_decision(correlation_id)
        if decision is not None:
            return DecisionOut.model_validate(decision)

        return self._escalated_placeholder(correlation_id=correlation_id, principal=principal)

    async def _poll_for_decision(self, correlation_id: str) -> dict[str, Any] | None:
        deadline = time.monotonic() + settings.chat_poll_budget_seconds
        delay = settings.chat_poll_initial_delay_seconds
        while True:
            found = await asyncio.to_thread(self._decisions.get_by_correlation_id, correlation_id)
            if found is not None:
                return found
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(delay, remaining))
            delay = min(delay * 2, settings.chat_poll_max_delay_seconds)

    def _escalated_placeholder(self, *, correlation_id: str, principal: Principal) -> DecisionOut:
        """§4's documented budget-exhaustion behavior: "return the partial
        narrative + status=ESCALATED" -- there is no partial narrative to
        surface without parsing Prime's trace (see module docstring), so
        this says so explicitly rather than fabricating one.
        """
        return DecisionOut(
            decision_id=correlation_id,
            correlation_id=correlation_id,
            principal=principal.arn,
            status="ESCALATED",
            narrative=(
                "Sentinel Prime's turn did not complete within the "
                f"{settings.chat_poll_budget_seconds:.0f}s REST budget. The turn may "
                "still be in flight; poll GET /decisions?next_token= or retry."
            ),
            decided_at=datetime.now(UTC).isoformat(),
        )
