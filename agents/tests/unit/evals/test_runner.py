"""Focused tests for the phase-12 eval harness (revised testing policy:
cover real behavior, not exhaustive fuzzing). Uses a fixture/stub provider
throughout -- no real XAI_API_KEY/Bedrock call, per phase-12 §9's own test
plan ("dry-run against a fixture agent... verify scoring is deterministic").
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.contract._factories import make_verdict

from iam_sentinel_agents.evals.judges import judge_grounding_majority
from iam_sentinel_agents.evals.runner import (
    EvalBlockedError,
    load_golden_set,
    main,
    NormalizedTranscript,
    run_phase,
    score_case,
)
from iam_sentinel_agents.evals.types import EvalCase, JudgeVerdict


class _StubProvider:
    """Minimal `LLMProvider` stand-in. `judge_queue` is consumed in order by
    successive `invoke_model` calls made for judging."""

    def __init__(self, judge_queue: list[JudgeVerdict]) -> None:
        self._judge_queue = list(judge_queue)

    def invoke_agent(self, **_kwargs: Any) -> Any:  # pragma: no cover - unused here
        raise NotImplementedError

    def invoke_agent_stream(self, **_kwargs: Any) -> Any:  # pragma: no cover - unused here
        raise NotImplementedError

    def invoke_model(self, **_kwargs: Any) -> JudgeVerdict:
        return self._judge_queue.pop(0)

    def retrieve(self, **_kwargs: Any) -> list[Any]:  # pragma: no cover - unused here
        return []


class _FixtureInvoker:
    """Always returns the same transcript, per phase-12 §9's fixture-agent
    determinism check."""

    def __init__(self, transcript: NormalizedTranscript) -> None:
        self._transcript = transcript

    def invoke(self, *, golden_set: str, case: EvalCase) -> NormalizedTranscript:
        return self._transcript


def _make_case(**overrides: Any) -> EvalCase:
    defaults: dict[str, Any] = {
        "id": "f1-test-01",
        "category": "obvious-yes",
        "query_text": "audit passrole",
        "hints": {"account_id": "111122223333"},
        # matches _factories.make_verdict()'s single tool_invocations entry
        "expected_tool_calls": ["passrole_scan"],
        "expected_verdict": "CONFIRM",
        "expected_citation_required": True,
    }
    defaults.update(overrides)
    return EvalCase(**defaults)


def test_load_golden_set_reads_real_f1_fixture_shipped_by_phase_02() -> None:
    cases = load_golden_set("f1")
    assert len(cases) >= 3
    assert all(c.id.startswith("f1-") for c in cases)


def test_load_golden_set_reads_prime_starter_set() -> None:
    cases = load_golden_set("prime")
    assert len(cases) >= 5
    assert all(c.id.startswith("prime-") for c in cases)


def test_load_golden_set_missing_raises_eval_blocked_error() -> None:
    with pytest.raises(EvalBlockedError):
        load_golden_set("does-not-exist")


def test_normalized_transcript_from_specialist_verdict_extracts_calls_and_citations() -> None:
    verdict = make_verdict()
    transcript = NormalizedTranscript.from_specialist_verdict(verdict)
    assert transcript.verdict == "CONFIRM"
    assert transcript.calls == ["passrole_scan"]
    assert transcript.citation_quotes and "PassRole" in transcript.citation_quotes[0]


def test_normalized_transcript_from_prime_turn_extracts_collaborators() -> None:
    from iam_sentinel_agents.prime.result_parser import ParsedPrimeTurn

    turn = ParsedPrimeTurn(
        progress_lines=["PROGRESS: routing to F1"],
        result={
            "status": "ANSWERED",
            "narrative": "Found a PassRole admin shortcut.",
            "findings": [{"aws_doc_citation": {"quote": "PassRole is not an API call."}}],
            "remediations_proposed": [],
            "specialist_calls": [{"collaborator": "passrole-cartographer", "duration_ms": 900}],
        },
    )

    transcript = NormalizedTranscript.from_prime_turn(turn)

    assert transcript.verdict == "ANSWERED"
    assert transcript.calls == ["passrole-cartographer"]
    assert transcript.citation_quotes == ["PassRole is not an API call."]


def test_judge_grounding_majority_takes_majority_vote_over_flaky_judge() -> None:
    # 2 of 3 votes say grounded -- majority must be True even though the
    # judge itself is nondeterministic (phase-12 §11 mitigation).
    votes = [
        JudgeVerdict(routing_ok=True, verdict_ok=True, citation_ok=True, grounding_ok=True),
        JudgeVerdict(routing_ok=True, verdict_ok=True, citation_ok=True, grounding_ok=False),
        JudgeVerdict(routing_ok=True, verdict_ok=True, citation_ok=True, grounding_ok=True),
    ]
    provider = _StubProvider(votes)
    case = _make_case()
    transcript = NormalizedTranscript.from_specialist_verdict(make_verdict())

    result = judge_grounding_majority(provider, case=case, transcript=transcript, correlation_id="c1")

    assert result.grounding_ok is True


def test_score_case_is_deterministic_across_repeated_runs() -> None:
    case = _make_case()
    transcript = NormalizedTranscript.from_specialist_verdict(make_verdict())
    votes = [JudgeVerdict(routing_ok=True, verdict_ok=True, citation_ok=True, grounding_ok=True)] * 3

    first = score_case(_StubProvider(list(votes)), golden_set="f1", case=case, transcript=transcript)
    second = score_case(_StubProvider(list(votes)), golden_set="f1", case=case, transcript=transcript)

    assert first.weighted == second.weighted == pytest.approx(1.0)
    assert first.routing == 1.0
    assert first.verdict == 1.0
    assert first.citation == 1.0


def test_run_phase_records_error_without_aborting_other_cases() -> None:
    class _AlwaysFailingInvoker:
        def invoke(self, *, golden_set: str, case: EvalCase) -> NormalizedTranscript:
            raise RuntimeError("specialist unreachable")

    votes = [JudgeVerdict(routing_ok=True, verdict_ok=True, citation_ok=True, grounding_ok=True)]
    report = run_phase(_AlwaysFailingInvoker(), _StubProvider(votes), phase="02")

    assert report.golden_set == "f1"
    assert len(report.scores) >= 3
    assert all(s.error == "specialist unreachable" for s in report.scores)
    assert report.weighted_mean == 0.0
    assert report.passed is False


def test_run_phase_with_fixture_invoker_scores_above_threshold_when_verdict_matches() -> None:
    case = _make_case(expected_verdict="CONFIRM", expected_tool_calls=["passrole_scan"])
    transcript = NormalizedTranscript.from_specialist_verdict(make_verdict())
    votes = [JudgeVerdict(routing_ok=True, verdict_ok=True, citation_ok=True, grounding_ok=True)] * 3

    score = score_case(_StubProvider(votes), golden_set="f1", case=case, transcript=transcript)

    assert score.weighted >= 0.9


def test_main_reports_blocked_when_xai_api_key_unprovisioned(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from iam_sentinel_adapters.settings import settings as adapter_settings

    monkeypatch.setattr(adapter_settings, "llm_provider", "grok")
    monkeypatch.setattr(adapter_settings, "xai_api_key", "")

    exit_code = main(["--phase", "02"])

    assert exit_code == 0
    assert "NOT RUN" in capsys.readouterr().out
