"""LLM-as-judge for the eval harness (phase-12 §6.5).

Routing/verdict/citation are scored deterministically in `runner.py`
against the parsed transcript -- only "does the narrative substantively
address what the golden case expects" (`grounding`) genuinely needs a
judge call, so that is the only dimension this module decides. It still
returns the full `JudgeVerdict` shape the spec's prompt asks for (all four
booleans + notes) so a caller can compare the judge's independent routing/
verdict/citation opinion against the deterministic scores as a sanity
signal, without the aggregate score ever depending on judge agreement for
those three dimensions -- LLM nondeterminism (phase-12 §11 risk) should not
be able to flip a deterministic pass/fail.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from iam_sentinel_adapters.settings import settings as adapter_settings

from iam_sentinel_agents.evals.types import JudgeVerdict

if TYPE_CHECKING:
    from iam_sentinel_adapters.llm.types import LLMProvider

    from iam_sentinel_agents.evals.runner import NormalizedTranscript
    from iam_sentinel_agents.evals.types import EvalCase

JUDGE_SYSTEM_PROMPT = """You are an eval judge for IAM Sentinel. You receive
the agent's transcript and the expected criteria. Return JSON:
{
  "routing_ok": boolean,
  "verdict_ok": boolean,
  "citation_ok": boolean,
  "grounding_ok": boolean,
  "notes": "one-sentence rationale"
}
Do not be lenient. If a citation is missing, citation_ok=false. If the
verdict differs from expected, verdict_ok=false."""


def build_judge_input(case: EvalCase, transcript: NormalizedTranscript) -> str:
    payload = {
        "eval_id": case.id,
        "query_text": case.query_text,
        "expected": {
            "tool_calls": case.expected_tool_calls,
            "verdict": case.expected_verdict,
            "min_severity": case.expected_min_severity,
            "citation_required": case.expected_citation_required,
            "notes": case.notes,
        },
        "actual": {
            "verdict": transcript.verdict,
            "calls": transcript.calls,
            "citation_quotes": transcript.citation_quotes,
            "narrative": transcript.narrative,
        },
    }
    return json.dumps(payload, sort_keys=True)


def judge_transcript(
    provider: LLMProvider, *, case: EvalCase, transcript: NormalizedTranscript, correlation_id: str
) -> JudgeVerdict:
    """Runs the judge prompt once. Callers wanting the phase-12 §11
    "retry-3-and-vote" flakiness mitigation call this three times and take
    the majority `grounding_ok` -- left to the caller rather than baked in
    here, since a fixture-backed unit test (phase-12 §9) needs to call this
    exactly once and get a deterministic result back.
    """
    result = provider.invoke_model(
        # Haiku, not Sonnet -- a judge scoring a single boolean per
        # dimension is exactly model_router.pick_model's cheap-tier case;
        # GrokProvider ignores model_id (settings.grok_model_id) entirely.
        model_id=adapter_settings.model_haiku_id,
        messages=[{"role": "user", "content": build_judge_input(case, transcript)}],
        correlation_id=correlation_id,
        system=JUDGE_SYSTEM_PROMPT,
        response_schema=JudgeVerdict,
    )
    if isinstance(result, JudgeVerdict):
        return result
    assert isinstance(result, str)  # response_schema was passed; a str means the provider ignored it
    return JudgeVerdict.model_validate_json(result)


def judge_grounding_majority(
    provider: LLMProvider,
    *,
    case: EvalCase,
    transcript: NormalizedTranscript,
    correlation_id: str,
    votes: int = 3,
) -> JudgeVerdict:
    """phase-12 §11 mitigation: temperature-0 judge is expected to be
    identical across repeats; running it `votes` times and taking a
    majority on `grounding_ok` catches the rare provider-side flake without
    trusting a single call."""
    results = [
        judge_transcript(
            provider, case=case, transcript=transcript, correlation_id=f"{correlation_id}-v{i}"
        )
        for i in range(votes)
    ]
    grounding_true = sum(1 for r in results if r.grounding_ok)
    majority = grounding_true * 2 > votes
    last = results[-1]
    return JudgeVerdict(
        routing_ok=last.routing_ok,
        verdict_ok=last.verdict_ok,
        citation_ok=last.citation_ok,
        grounding_ok=majority,
        notes=last.notes,
    )
