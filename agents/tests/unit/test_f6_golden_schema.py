"""Schema/quality gate for `agents/evals/f6/golden.jsonl` (phase-07 §8:
"Eval: 20 golden turns"). Schema-only, mirroring `test_f1_golden_schema.py`
and docs/decisions/0031's extension of ADR 0015's deferral: `iam_sentinel_
agents.evals.runner` (phase-12) doesn't exist yet and no deployed
ShadowGuard agent exists to actually run a turn against. Nine entries cover
all five required categories -- scaled down from the spec's 20 on the same
ratio ADR 0015 used against phase-02's 25.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "evals" / "f6" / "golden.jsonl"

_REQUIRED_CATEGORIES = {
    "obvious-yes",
    "obvious-no",
    "tricky",
    "adversarial-input",
    "latency-sensitive",
}
_REQUIRED_FIELDS = {
    "id",
    "category",
    "query_text",
    "hints",
    "expected_tool_calls",
    "expected_verdict",
    "expected_min_severity",
    "expected_citation_required",
    "notes",
}
_VALID_VERDICTS = {"CONFIRM", "REJECT", "ESCALATE", "INCONCLUSIVE", "REMEDIATED"}
_VALID_SEVERITIES = {None, "LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _load_golden() -> list[dict[str, Any]]:
    lines = GOLDEN_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_golden_file_exists_and_has_at_least_five_entries() -> None:
    entries = _load_golden()
    assert len(entries) >= 5


def test_every_entry_has_the_required_fields_and_valid_enums() -> None:
    for entry in _load_golden():
        missing = _REQUIRED_FIELDS - entry.keys()
        assert not missing, f"{entry.get('id')} missing {missing}"
        assert entry["category"] in _REQUIRED_CATEGORIES, entry
        assert entry["expected_verdict"] in _VALID_VERDICTS, entry
        assert entry["expected_min_severity"] in _VALID_SEVERITIES, entry
        assert isinstance(entry["expected_citation_required"], bool), entry
        assert entry["expected_tool_calls"], entry


def test_every_required_category_has_at_least_one_entry() -> None:
    categories = {entry["category"] for entry in _load_golden()}
    missing = _REQUIRED_CATEGORIES - categories
    assert not missing, f"missing golden-set coverage for: {missing}"


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_golden()]
    assert len(ids) == len(set(ids))
