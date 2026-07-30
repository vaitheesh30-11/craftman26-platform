"""Thin orchestration client wrapping `LLMProvider.invoke_agent` /
`invoke_agent_stream` for Sentinel Prime (phase-01 §3, §5 Step 5).

Prime's own specialist routing/fan-out happens inside Bedrock's SUPERVISOR
collaboration mode once deployed (docs/decisions/0013) -- this class is
the boundary agents/ owns: turning a `SentinelQuery` into the
`sessionState` shape phase-01 §3.1 specifies, sanitizing the query text as
untrusted input before it ever reaches a prompt, and parsing the model's
completion via `result_parser`. It never calls boto3 directly -- every
Bedrock call goes through `iam_sentinel_adapters.llm`.

Deliberately NOT wired to `PrimePostTurnProcessor` here (see
docs/decisions/0013): the RESULT JSON block's `findings`/
`remediations_proposed` are plain dicts the model echoes verbatim from
specialist verdicts (phase-01 §5), not full `SpecialistVerdict` Pydantic
objects with `tool_invocations`/Zelkova checks -- those live in the
Bedrock trace envelope (`BedrockAgentResponse.trace`), whose real shape
phase-01 §4 step 3 itself flags as unverified against a live
`enableTrace=true` response. Reconstructing `SpecialistVerdict` instances
from a guessed trace shape would risk silently fabricating tool-invocation
data `output_validator` and `Finding`'s manifest check exist specifically
to prevent. `PrimePostTurnProcessor.process` is fully built and tested
against explicit verdicts; wiring it to real trace parsing is deferred
until a deployed Prime's trace can be inspected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.prompts.sanitizer import sanitize_untrusted

from iam_sentinel_agents.prime.result_parser import parse_prime_completion, ParsedPrimeTurn
from iam_sentinel_agents.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_adapters.llm.types import LLMProvider

    from iam_sentinel_agents.contracts.query import SentinelQuery


class PrimeSupervisor:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        agent_id: str | None = None,
        alias_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._agent_id = agent_id or settings.prime_agent_id
        self._alias_id = alias_id or settings.prime_agent_alias_id

    def ask(self, query: SentinelQuery) -> ParsedPrimeTurn:
        # `query.query_text` is auditor-supplied, hence untrusted (prompt
        # rule 7: only content inside <untrusted_context> is data, but the
        # top-level human turn is exactly the kind of input the sanitizer
        # exists to gate -- see agents/tests/prompt_injection).
        sanitized_query_text = sanitize_untrusted(query.query_text)

        response = self._provider.invoke_agent(
            agent_id=self._agent_id,
            alias_id=self._alias_id,
            session_id=query.correlation_id,
            input_text=sanitized_query_text,
            correlation_id=query.correlation_id,
            session_state={
                "sessionAttributes": {"correlation_id": query.correlation_id},
                "promptSessionAttributes": {"principal": query.principal},
            },
            enable_trace=True,
        )

        return parse_prime_completion(response.completion)
