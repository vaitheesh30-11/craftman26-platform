"""Schema/quality gate for `agents/evals/memory/golden.jsonl` (phase-14
§7: "Vector: 20 curated similar-query pairs; k-NN top-1 must be the
intended prior record for >= 18/20 pairs"). Per the revised testing
policy and docs/decisions/0015 (F1's identical deferral) / 0010 (RAG KB's
identical deferral for its own vector search), this is schema-only:
`iam_sentinel_agents.evals.runner` (phase-12) doesn't exist yet, and the
OpenSearch Serverless `sentinel-episodic-vector` collection this golden
set is meant to exercise is itself deferred per
`docs/decisions/0006` ("the OSS k-NN read half is a documented interface
stub"). No deployed collection exists to actually run k-NN search against.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "evals" / "memory" / "golden.jsonl"

_REQUIRED_CATEGORIES = {"similar-pair", "distinct-pair"}
_REQUIRED_FIELDS = {
    "id",
    "category",
    "query_text",
    "prior_narrative_excerpt",
    "expected_top1_decision_id",
    "expected_within_threshold",
    "notes",
}


def _load_golden() -> list[dict[str, Any]]:
    lines = GOLDEN_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_golden_file_exists_and_has_at_least_twenty_entries() -> None:
    entries = _load_golden()
    assert len(entries) >= 20


def test_every_entry_has_the_required_fields_and_valid_enums() -> None:
    for entry in _load_golden():
        missing = _REQUIRED_FIELDS - entry.keys()
        assert not missing, f"{entry.get('id')} missing {missing}"
        assert entry["category"] in _REQUIRED_CATEGORIES, entry
        assert isinstance(entry["expected_within_threshold"], bool), entry
        assert entry["query_text"], entry
        assert entry["prior_narrative_excerpt"], entry


def test_every_required_category_has_at_least_one_entry() -> None:
    categories = {entry["category"] for entry in _load_golden()}
    missing = _REQUIRED_CATEGORIES - categories
    assert not missing, f"missing golden-set coverage for: {missing}"


def test_similar_pairs_expect_a_top1_match_and_distinct_pairs_do_not() -> None:
    for entry in _load_golden():
        if entry["category"] == "similar-pair":
            assert entry["expected_within_threshold"] is True, entry
            assert entry["expected_top1_decision_id"] is not None, entry
        else:
            assert entry["expected_within_threshold"] is False, entry
            assert entry["expected_top1_decision_id"] is None, entry


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_golden()]
    assert len(ids) == len(set(ids))
