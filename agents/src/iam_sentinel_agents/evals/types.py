"""Typed shapes for the eval harness: golden-set rows and score reports.

These are eval-only -- they never appear in a real `DecisionRecord` -- so
they live outside `contracts/` deliberately (phase-12 §6.2's aspirational
golden-case shape doesn't match what agents phase-02 (F1) actually shipped
in `agents/evals/f1/golden.jsonl`, and every later specialist copied F1's
shape verbatim rather than the spec's. `EvalCase` models the shape that
exists on disk today, not the one the txt file describes).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EvalCase(BaseModel):
    """One line of `agents/evals/{phase}/golden.jsonl`."""

    model_config = ConfigDict(extra="ignore", frozen=True, str_strip_whitespace=True)

    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    hints: dict[str, str] = Field(default_factory=dict)
    expected_tool_calls: list[str] = Field(default_factory=list)
    # Deliberately `str`, not `contracts.common.Verdict` -- Prime's golden
    # set (agents/evals/prime) scores against `DecisionStatus` values
    # (ANSWERED/ESCALATED/...), a different enum than a specialist's
    # `Verdict`. One eval-case shape covers both without a union.
    expected_verdict: str = Field(min_length=1)
    expected_min_severity: str | None = None
    expected_citation_required: bool = False
    notes: str = ""


class JudgeVerdict(BaseModel):
    """Structured output every judge call must return (phase-12 §6.5)."""

    model_config = ConfigDict(extra="ignore")

    routing_ok: bool
    verdict_ok: bool
    citation_ok: bool
    grounding_ok: bool
    notes: str = Field(default="", max_length=512)


class ScoreBreakdown(BaseModel):
    """Per-case score, weighted per phase-12 §6.3 (routing 0.2, verdict 0.4,
    citation 0.2, grounding 0.2)."""

    model_config = ConfigDict(frozen=True)

    eval_id: str
    routing: float = Field(ge=0.0, le=1.0)
    verdict: float = Field(ge=0.0, le=1.0)
    citation: float = Field(ge=0.0, le=1.0)
    grounding: float = Field(ge=0.0, le=1.0)
    judge_notes: str = ""
    error: str | None = None

    @property
    def weighted(self) -> float:
        return 0.2 * self.routing + 0.4 * self.verdict + 0.2 * self.citation + 0.2 * self.grounding


class PhaseReport(BaseModel):
    """Aggregate result of one `--phase` run."""

    model_config = ConfigDict(frozen=True)

    phase: str
    golden_set: str
    scores: list[ScoreBreakdown]
    passing_threshold: float = 0.9

    @property
    def weighted_mean(self) -> float:
        if not self.scores:
            return 0.0
        return sum(score.weighted for score in self.scores) / len(self.scores)

    @property
    def passed(self) -> bool:
        return self.weighted_mean >= self.passing_threshold
