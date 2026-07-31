"""Stream fan-out service (phase-02 §2 deliverable): forwards Bedrock
streaming chunks to `apigatewaymanagementapi:PostToConnection`.

Per ADR 0018's precedent for `ChatService`, this does not parse Prime's
completion text into `Finding`/`SpecialistVerdict` objects -- the post-turn
Lambda (`agents/src/iam_sentinel_agents/prime/post_turn.py`) already does
that and writes the resulting `DecisionRecord` to `SentinelDecisions`
out-of-band. Once `invoke_agent_stream`'s final chunk arrives, this polls
that table the same way `ChatService._poll_for_decision` does, just with a
much tighter budget -- the caller is already watching a live socket.

Principal binding (phase-02 §8 "cross-connection principal leakage" risk):
`stream_chat`'s `principal`/`session_id` arguments always come from the
caller's own `SentinelConnections` row (see `ws/default.py`), never from the
client-supplied frame body -- there is no code path here that could bind a
Bedrock session to an attacker-chosen identity.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from iam_sentinel_adapters.errors import (
    ConnectionGoneError,
    GuardrailInterventionError,
    SanitizerRejection,
    SentinelAdapterError,
)
from iam_sentinel_adapters.prompts.sanitizer import sanitize_untrusted

from iam_sentinel_backend.settings import settings
from iam_sentinel_backend.ws.protocol import encode_event

if TYPE_CHECKING:
    from iam_sentinel_adapters.apigw.management import ManagementApiClient
    from iam_sentinel_adapters.ddb.decisions import DecisionsClient
    from iam_sentinel_adapters.ddb.decisions_in_flight import DecisionsInFlightClient
    from iam_sentinel_adapters.llm.types import LLMProvider

# Headroom reserved for the `event: ...\ndata: ` envelope plus JSON
# punctuation around a truncated string -- generous rather than exact, since
# under-truncating by a few bytes is free and over-running the 128 KB frame
# cap (phase-02 §4) is not.
_FRAME_ENVELOPE_HEADROOM_BYTES = 256


class StreamFanoutService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        decisions_client: DecisionsClient,
        decisions_in_flight_client: DecisionsInFlightClient,
        management_client: ManagementApiClient,
        rate_limit_per_second: float | None = None,
        max_frame_bytes: int | None = None,
    ) -> None:
        self._provider = provider
        self._decisions = decisions_client
        self._in_flight = decisions_in_flight_client
        self._management = management_client
        self._rate_limit_per_second = rate_limit_per_second or settings.ws_rate_limit_per_second
        self._max_frame_bytes = max_frame_bytes or settings.ws_max_frame_bytes

    def stream_chat(
        self,
        *,
        connection_id: str,
        endpoint_url: str,
        principal: str,
        session_id: str,
        correlation_id: str,
        query_text: str,
    ) -> None:
        try:
            sanitized_query_text = sanitize_untrusted(query_text)
        except SanitizerRejection as exc:
            self._send_error(
                endpoint_url, connection_id, code="SANITIZER_REJECTED", message=str(exc)
            )
            return

        self._in_flight.start(correlation_id, {"principal": principal, "session_id": session_id})
        try:
            self._fan_out(
                connection_id=connection_id,
                endpoint_url=endpoint_url,
                session_id=session_id,
                correlation_id=correlation_id,
                sanitized_query_text=sanitized_query_text,
            )
        finally:
            self._in_flight.complete(correlation_id)

    def cancel(self, *, correlation_id: str) -> None:
        self._in_flight.cancel(correlation_id)

    def send_pong(self, *, endpoint_url: str, connection_id: str) -> None:
        self._send(endpoint_url, connection_id, "pong", {})

    def send_error(
        self,
        *,
        endpoint_url: str,
        connection_id: str,
        code: str,
        message: str,
        correlation_id: str = "",
    ) -> None:
        self._send_error(
            endpoint_url, connection_id, code=code, message=message, correlation_id=correlation_id
        )

    # ------------------------------------------------------------------
    def _fan_out(
        self,
        *,
        connection_id: str,
        endpoint_url: str,
        session_id: str,
        correlation_id: str,
        sanitized_query_text: str,
    ) -> None:
        min_interval = 1.0 / self._rate_limit_per_second
        next_allowed_send = time.monotonic()
        # `correlation_id` is minted server-side (`ws/default.py`) and, until
        # now, was never surfaced to the client before the turn completed --
        # a real protocol gap frontend phase-01 found while building the
        # Cancel button (`POST {action: "cancel", correlation_id}` per
        # phase-01 §4 has nothing to send without this). One extra frame,
        # sent before invoking Prime, closes it.
        self._send(endpoint_url, connection_id, "started", {"correlation_id": correlation_id})
        try:
            chunks = self._provider.invoke_agent_stream(
                agent_id=settings.prime_agent_id,
                alias_id=settings.prime_agent_alias_id,
                session_id=f"{connection_id}::{session_id}",
                input_text=sanitized_query_text,
                correlation_id=correlation_id,
            )
            for chunk in chunks:
                if self._in_flight.is_canceled(correlation_id):
                    self._send_error(
                        endpoint_url, connection_id, code="CANCELED", message="canceled by client"
                    )
                    return
                if chunk.guardrail_intervened:
                    self._send_error(
                        endpoint_url,
                        connection_id,
                        code="GUARDRAIL_INTERVENTION",
                        message="Guardrail intervened",
                    )
                    return
                if chunk.is_final:
                    break
                if not chunk.text:
                    continue
                now = time.monotonic()
                if now < next_allowed_send:
                    time.sleep(next_allowed_send - now)
                if not self._send(
                    endpoint_url, connection_id, "progress", self._truncate(chunk.text)
                ):
                    return  # connection gone; nothing left to fan out to
                next_allowed_send = time.monotonic() + min_interval
        except GuardrailInterventionError as exc:
            self._send_error(
                endpoint_url, connection_id, code="GUARDRAIL_INTERVENTION", message=str(exc)
            )
            return
        except SentinelAdapterError as exc:
            self._send_error(
                endpoint_url, connection_id, code="PRIME_INVOCATION_FAILED", message=str(exc)
            )
            return

        decision = self._poll_for_decision(correlation_id)
        if decision is not None:
            self._send(endpoint_url, connection_id, "result", decision)
        else:
            self._send_error(
                endpoint_url,
                connection_id,
                code="ESCALATED",
                message=(
                    "Sentinel Prime's turn did not complete within the "
                    f"{settings.ws_result_poll_budget_seconds:.0f}s streaming result budget."
                ),
            )

    def _poll_for_decision(self, correlation_id: str) -> dict[str, Any] | None:
        deadline = time.monotonic() + settings.ws_result_poll_budget_seconds
        delay = settings.ws_result_poll_initial_delay_seconds
        while True:
            found = self._decisions.get_by_correlation_id(correlation_id)
            if found is not None:
                return found
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, settings.ws_result_poll_max_delay_seconds)

    def _send_error(
        self,
        endpoint_url: str,
        connection_id: str,
        *,
        code: str,
        message: str,
        correlation_id: str = "",
    ) -> None:
        self._send(
            endpoint_url,
            connection_id,
            "error",
            {"code": code, "message": message, "correlation_id": correlation_id},
        )

    def _send(
        self, endpoint_url: str, connection_id: str, event: str, data: str | dict[str, object]
    ) -> bool:
        try:
            self._management.post_to_connection(
                endpoint_url=endpoint_url,
                connection_id=connection_id,
                data=encode_event(event, data),
            )
        except ConnectionGoneError:
            return False
        return True

    def _truncate(self, text: str) -> str:
        budget = max(self._max_frame_bytes - _FRAME_ENVELOPE_HEADROOM_BYTES, 0)
        encoded = text.encode()
        if len(encoded) <= budget:
            return text
        return encoded[:budget].decode("utf-8", errors="ignore") + "…(truncated)"
