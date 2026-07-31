"""The eval runner every prior agents phase deferred to (phase-12 §6.1;
docs/EXECUTION_PLAN.txt §4: "MUST score >=0.9 on the phase's golden set").

`python -m iam_sentinel_agents.evals.runner --phase <NN>` loads
`agents/evals/{golden_set}/golden.jsonl`, invokes the specialist (or Prime)
through the existing `LLMProvider` adapter (Grok locally, Bedrock in AWS --
`SENTINEL_LLM_PROVIDER`, adapters phase-01), and scores the four
dimensions from phase-12 §6.3: routing (0.2), verdict (0.4), citation
(0.2), grounding (0.2 -- LLM-as-judge, `judges.py`).

Routing/verdict/citation are scored deterministically against the already-
typed `SpecialistVerdict` (or Prime's `ParsedPrimeTurn`) the provider
returns -- no judge call needed for those three; the model's own JSON
structure and Pydantic's field validators (`Finding.aws_doc_citation`,
`Verdict` enum) are the ground truth. Only grounding needs a second LLM
call.

If `XAI_API_KEY` is unprovisioned (ADR 0007; still true as of ADR 0037),
every phase reports `blocked` rather than inventing a score -- see
docs/decisions/0037-agents-phase-12-observability-evals-scope.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TYPE_CHECKING

from iam_sentinel_adapters.settings import settings as adapter_settings

from iam_sentinel_agents.contracts.task import SpecialistTask, UntrustedContextBlock
from iam_sentinel_agents.errors import SentinelAgentError
from iam_sentinel_agents.evals.judges import judge_grounding_majority
from iam_sentinel_agents.evals.types import EvalCase, PhaseReport, ScoreBreakdown
from iam_sentinel_agents.ids import new_ulid
from iam_sentinel_agents.prime.result_parser import parse_prime_completion
from iam_sentinel_agents.prompts.registry import load_prime_prompt

if TYPE_CHECKING:
    from collections.abc import Iterable

    from iam_sentinel_adapters.llm.types import LLMProvider

    from iam_sentinel_agents.contracts.common import FeatureID
    from iam_sentinel_agents.prime.result_parser import ParsedPrimeTurn

_EVALS_ROOT = Path(__file__).resolve().parents[3] / "evals"
_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "specialists"

# Sprint-numbering map (docs/decisions/0013, 0015, 0024-0031): phase-01 is
# Prime, phase-02..09 are F1..F8 in build order -- not feature-ID order.
# This is the same mapping the orchestrating task instructions use
# ("--phase 01 through --phase 09").
PHASE_TO_GOLDEN: dict[str, str] = {
    "01": "prime",
    "02": "f1",
    "03": "f2",
    "04": "f3",
    "05": "f4",
    "06": "f5",
    "07": "f6",
    "08": "f7",
    "09": "f8",
}
GOLDEN_TO_FEATURE_ID: dict[str, FeatureID] = {
    "f1": "F1",
    "f2": "F2",
    "f3": "F3",
    "f4": "F4",
    "f5": "F5",
    "f6": "F6",
    "f7": "F7",
    "f8": "F8",
}
_PROMPT_FILENAMES: dict[str, str] = {
    "f1": "f1_passrole.txt",
    "f2": "f2_org_context.txt",
    "f3": "f3_data_event.txt",
    "f4": "f4_scp_impact.txt",
    "f5": "f5_session_kill.txt",
    "f6": "f6_shadow_guard.txt",
    "f7": "f7_collision.txt",
    "f8": "f8_slr_guardian.txt",
}
PASSING_THRESHOLD = 0.9


class EvalBlockedError(SentinelAgentError):
    """Raised when a phase cannot be run for a real, pre-existing reason
    (no XAI_API_KEY, no golden set on disk yet) -- never caught and turned
    into a fabricated score."""


@dataclass(frozen=True)
class NormalizedTranscript:
    """One shape both a specialist's `SpecialistVerdict` and Prime's
    `ParsedPrimeTurn` reduce to, so scoring doesn't need two code paths."""

    verdict: str
    calls: list[str] = field(default_factory=list)
    citation_quotes: list[str] = field(default_factory=list)
    narrative: str = ""

    @classmethod
    def from_specialist_verdict(cls, verdict: object) -> NormalizedTranscript:
        from iam_sentinel_agents.contracts.verdict import SpecialistVerdict

        if not isinstance(verdict, SpecialistVerdict):
            raise EvalBlockedError(f"expected SpecialistVerdict, got {type(verdict)!r}")
        return cls(
            verdict=verdict.verdict,
            calls=[t.tool_name for t in verdict.tool_invocations],
            citation_quotes=[f.aws_doc_citation.quote for f in verdict.findings],
            narrative=verdict.reason + " " + " ".join(f.detail for f in verdict.findings),
        )

    @classmethod
    def from_prime_turn(cls, turn: ParsedPrimeTurn) -> NormalizedTranscript:
        result = turn.result
        specialist_calls = result.get("specialist_calls", [])
        collaborators = [
            str(c["collaborator"])
            for c in specialist_calls
            if isinstance(c, dict) and "collaborator" in c
        ]
        findings = result.get("findings", [])
        citations = [
            f["aws_doc_citation"]["quote"]
            for f in findings
            if isinstance(f, dict) and isinstance(f.get("aws_doc_citation"), dict)
        ]
        return cls(
            verdict=str(result.get("status", "")),
            calls=collaborators,
            citation_quotes=citations,
            narrative=str(result.get("narrative", "")),
        )


class SpecialistInvoker(Protocol):
    def invoke(self, *, golden_set: str, case: EvalCase) -> NormalizedTranscript: ...


class LiveInvoker:
    """Invokes the real specialist prompt (or Prime's) through
    `LLMProvider.invoke_model`, per docs/decisions/0007's pattern: Grok
    locally emulates the call in-process, Bedrock does the real
    `InvokeModel`. This is the harness `--phase` actually runs when
    `XAI_API_KEY`/AWS creds are available.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def invoke(self, *, golden_set: str, case: EvalCase) -> NormalizedTranscript:
        correlation_id = new_ulid()
        if golden_set == "prime":
            return self._invoke_prime(case, correlation_id)
        return self._invoke_specialist(golden_set, case, correlation_id)

    def _invoke_specialist(
        self, golden_set: str, case: EvalCase, correlation_id: str
    ) -> NormalizedTranscript:
        from iam_sentinel_agents.contracts.verdict import SpecialistVerdict

        feature_id = GOLDEN_TO_FEATURE_ID[golden_set]
        prompt_path = _PROMPTS_ROOT / _PROMPT_FILENAMES[golden_set]
        system_prompt = prompt_path.read_text(encoding="utf-8")

        task = SpecialistTask(
            correlation_id=correlation_id,
            feature_id=feature_id,
            trusted_input=dict(case.hints),
            untrusted_context=[UntrustedContextBlock(type="query", body=case.query_text[:32_768])],
        )
        user_message = (
            f"<trusted_input>{json.dumps(task.trusted_input)}</trusted_input>\n"
            f"<untrusted_context>{case.query_text}</untrusted_context>"
        )
        result = self._provider.invoke_model(
            model_id=adapter_settings.model_sonnet_id,
            messages=[{"role": "user", "content": user_message}],
            correlation_id=correlation_id,
            system=system_prompt,
            response_schema=SpecialistVerdict,
        )
        if isinstance(result, SpecialistVerdict):
            return NormalizedTranscript.from_specialist_verdict(result)
        assert isinstance(result, str)  # response_schema was passed; a non-SpecialistVerdict BaseModel would be a provider bug
        return NormalizedTranscript.from_specialist_verdict(SpecialistVerdict.model_validate_json(result))

    def _invoke_prime(self, case: EvalCase, correlation_id: str) -> NormalizedTranscript:
        system_prompt = load_prime_prompt()
        user_message = (
            f"<trusted_input>{json.dumps(dict(case.hints))}</trusted_input>\n"
            f"<untrusted_context>{case.query_text}</untrusted_context>"
        )
        completion = self._provider.invoke_model(
            model_id=adapter_settings.model_sonnet_id,
            messages=[{"role": "user", "content": user_message}],
            correlation_id=correlation_id,
            system=system_prompt,
        )
        text = completion if isinstance(completion, str) else completion.model_dump_json()
        turn = parse_prime_completion(text)
        return NormalizedTranscript.from_prime_turn(turn)


def load_golden_set(golden_set: str) -> list[EvalCase]:
    path = _EVALS_ROOT / golden_set / "golden.jsonl"
    if not path.exists():
        raise EvalBlockedError(f"no golden set at {path}")
    cases: list[EvalCase] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            cases.append(EvalCase.model_validate_json(stripped))
        except ValueError as exc:
            raise EvalBlockedError(f"{path}:{line_no}: malformed golden case: {exc}") from exc
    if not cases:
        raise EvalBlockedError(f"{path} is empty")
    return cases


def _score_routing(case: EvalCase, transcript: NormalizedTranscript) -> float:
    if not case.expected_tool_calls:
        return 1.0
    expected = set(case.expected_tool_calls)
    actual = set(transcript.calls)
    hit = len(expected & actual)
    return hit / len(expected)


def _score_verdict(case: EvalCase, transcript: NormalizedTranscript) -> float:
    return 1.0 if transcript.verdict == case.expected_verdict else 0.0


def _score_citation(case: EvalCase, transcript: NormalizedTranscript) -> float:
    if not case.expected_citation_required:
        return 1.0
    return 1.0 if any(q.strip() for q in transcript.citation_quotes) else 0.0


def score_case(
    provider: LLMProvider, *, golden_set: str, case: EvalCase, transcript: NormalizedTranscript
) -> ScoreBreakdown:
    routing = _score_routing(case, transcript)
    verdict = _score_verdict(case, transcript)
    citation = _score_citation(case, transcript)

    judge = judge_grounding_majority(
        provider, case=case, transcript=transcript, correlation_id=f"judge-{golden_set}-{case.id}"
    )
    grounding = 1.0 if judge.grounding_ok else 0.0

    return ScoreBreakdown(
        eval_id=case.id,
        routing=routing,
        verdict=verdict,
        citation=citation,
        grounding=grounding,
        judge_notes=judge.notes,
    )


def run_phase(
    invoker: SpecialistInvoker, provider: LLMProvider, *, phase: str, golden_set: str | None = None
) -> PhaseReport:
    resolved_golden_set = golden_set or PHASE_TO_GOLDEN.get(phase, phase)
    cases = load_golden_set(resolved_golden_set)

    scores: list[ScoreBreakdown] = []
    for case in cases:
        try:
            transcript = invoker.invoke(golden_set=resolved_golden_set, case=case)
            scores.append(score_case(provider, golden_set=resolved_golden_set, case=case, transcript=transcript))
        except Exception as exc:  # noqa: BLE001 -- one bad case must not abort the whole phase report
            scores.append(
                ScoreBreakdown(eval_id=case.id, routing=0.0, verdict=0.0, citation=0.0, grounding=0.0, error=str(exc))
            )

    return PhaseReport(
        phase=phase, golden_set=resolved_golden_set, scores=scores, passing_threshold=PASSING_THRESHOLD
    )


def _print_report(report: PhaseReport) -> None:
    print(f"phase {report.phase} ({report.golden_set}): weighted_mean={report.weighted_mean:.3f} "
          f"pass={report.passed} n={len(report.scores)}")
    for score in report.scores:
        flag = "ERR" if score.error else ("OK" if score.weighted >= PASSING_THRESHOLD else "LOW")
        print(
            f"  [{flag}] {score.eval_id}: weighted={score.weighted:.2f} "
            f"routing={score.routing:.1f} verdict={score.verdict:.1f} "
            f"citation={score.citation:.1f} grounding={score.grounding:.1f}"
            + (f" error={score.error}" if score.error else "")
        )


def main(argv: Iterable[str] | None = None) -> int:
    from iam_sentinel_adapters.llm.factory import get_provider

    parser = argparse.ArgumentParser(prog="iam_sentinel_agents.evals.runner")
    parser.add_argument(
        "--phase",
        required=True,
        help="two-digit sprint phase (01=prime, 02..09=F1..F8) or a golden-set slug (f1..f8, prime)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    phase = args.phase

    if adapter_settings.llm_provider == "grok" and not adapter_settings.xai_api_key:
        print(
            f"phase {phase}: NOT RUN -- XAI_API_KEY unprovisioned "
            "(ADR 0007, ADR 0037). This is a real, pre-existing blocker, not a failure."
        )
        return 0

    provider = get_provider()
    report = run_phase(LiveInvoker(provider), provider, phase=phase)
    _print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
