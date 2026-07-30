"""Schema/quality gate for the prompt-injection corpus (agents phase-11
§6; see ADR 0004 for why this is a schema check rather than an end-to-end
run through Prime — no Prime or deployed Guardrail exists yet).
"""

from __future__ import annotations

import json
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "corpus.jsonl"

_VALID_OUTCOMES = {"sanitizer_reject", "guardrail_intervened", "refusal"}
_VALID_FEATURE_SCOPES = {"ALL", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"}
_REQUIRED_CATEGORIES = {
    "direct_instruction_override",
    "indirect_via_untrusted_context",
    "role_name_as_instruction",
    "base64_encoded_override",
    "homoglyph_attack",
    "rtl_override_attack",
    "xml_tag_closure",
    "json_injection",
}


def _load_corpus() -> list[dict[str, str]]:
    lines = CORPUS_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_corpus_file_exists_and_is_non_empty() -> None:
    entries = _load_corpus()
    assert len(entries) > 0


def test_every_entry_has_the_required_fields() -> None:
    for entry in _load_corpus():
        assert entry["payload"], entry
        assert entry["expected_outcome"] in _VALID_OUTCOMES, entry
        assert entry["feature_id_scope"] in _VALID_FEATURE_SCOPES, entry
        assert entry["category"] in _REQUIRED_CATEGORIES, entry


def test_every_required_category_has_at_least_one_payload() -> None:
    categories = {entry["category"] for entry in _load_corpus()}
    missing = _REQUIRED_CATEGORIES - categories
    assert not missing, f"missing corpus coverage for: {missing}"


def test_no_duplicate_payloads() -> None:
    payloads = [entry["payload"] for entry in _load_corpus()]
    assert len(payloads) == len(set(payloads))
