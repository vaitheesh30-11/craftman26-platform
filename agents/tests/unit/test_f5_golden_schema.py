"""Schema/quality gate for `agents/evals/f5/golden.jsonl` (phase-06 §8:
"20 golden turns focused on trigger routing and denylist enforcement").
Per the revised testing policy and the ADR 0015/0004 precedent, this is
schema-only: `iam_sentinel_agents.evals.runner` (phase-12) doesn't exist
yet and no deployed Prime/F5 agent exists to run a turn against.

Deviation from `test_f1_golden_schema.py`'s otherwise-identical shape:
F1 is read-only and always calls both its tools even on a clean scan, so
its `expected_tool_calls` is never empty. F5 is write-capable and gated by
`confirm_kill` (REASONING CONTRACT) -- an unconfirmed request must produce
verdict=REJECT with ZERO tool calls, not a scan that happens to find
nothing. This test allows an empty `expected_tool_calls` list precisely
when `expected_verdict == "REJECT"`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "evals" / "f5" / "golden.jsonl"

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
        assert isinstance(entry["expected_tool_calls"], list), entry
        if entry["expected_verdict"] != "REJECT":
            assert entry["expected_tool_calls"], entry


def test_reject_entries_call_no_tools() -> None:
    for entry in _load_golden():
        if entry["expected_verdict"] == "REJECT":
            assert entry["expected_tool_calls"] == [], entry


def test_every_required_category_has_at_least_one_entry() -> None:
    categories = {entry["category"] for entry in _load_golden()}
    missing = _REQUIRED_CATEGORIES - categories
    assert not missing, f"missing golden-set coverage for: {missing}"


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_golden()]
    assert len(ids) == len(set(ids))
