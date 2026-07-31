"""Schema/quality test for `evals/cost_guardrails/golden.jsonl`
(agents-phase-16, docs/decisions/0032).

Phase-12's eval runner (`agents/src/iam_sentinel_agents/evals/runner.py`)
does not exist yet on this branch -- it is scheduled for sprint step
"agents phase-12", still ahead of this one, and no earlier phase built it
either (same deferred-dependency pattern every prior phase in this sprint
has used: see docs/decisions/0004, 0010). This test therefore checks the
corpus's own internal quality -- required fields present, ids unique,
category coverage -- rather than running it through a runner that isn't
built. Each case's behavioral assertion already has a dedicated unit test
cross-referenced in its own `notes` field (`test_budget_gate.py`,
`test_model_router.py`, `test_cost_report.py`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_GOLDEN_PATH = (
    Path(__file__).resolve().parents[2] / "evals" / "cost_guardrails" / "golden.jsonl"
)
_REQUIRED_FIELDS = ("id", "category", "scenario", "inputs", "expected_outcome", "notes")
_MIN_CASES = 5


def _load_cases() -> list[dict[str, Any]]:
    lines = _GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_golden_file_has_at_least_five_cases() -> None:
    assert len(_load_cases()) >= _MIN_CASES


def test_every_case_has_required_fields() -> None:
    for case in _load_cases():
        missing = [field for field in _REQUIRED_FIELDS if field not in case]
        assert not missing, f"case {case.get('id')!r} missing fields: {missing}"


def test_case_ids_are_unique() -> None:
    ids = [case["id"] for case in _load_cases()]
    assert len(ids) == len(set(ids))


def test_cases_cover_every_budget_layer() -> None:
    """phase-16 §3's three layers plus the two guardrails this phase adds
    on top (circuit breakers, cost-aware routing) each need at least one
    case -- a corpus that only ever exercised the correlation cap would
    silently under-test the daily/breaker/router paths.
    """
    categories = {case["category"] for case in _load_cases()}
    required = {
        "correlation-cap",
        "daily-cap",
        "circuit-breaker",
        "runaway-tool-invocations",
    }
    assert required.issubset(categories)
