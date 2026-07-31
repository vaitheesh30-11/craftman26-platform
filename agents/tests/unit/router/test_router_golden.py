"""Golden-eval gate for `RequestRouter.classify` (agents phase-15 §8 Test
Plan item 1: "router policy applied to 30 curated inputs; verify `mode` and
`dispatch_target`"). Unlike F1-F8's own `evals/{feature}/golden.jsonl`
(schema-only per `docs/decisions` -- no eval runner exists yet and no
Bedrock Agent is deployed), `classify()` is pure Python with zero AWS/LLM
dependencies, so this golden set is run for real, not just schema-checked.

`rng=lambda: 1.0` disables shadow-sampling upgrades for every case here:
this file is about the fast/slow/target decision tree, not the sampling
overlay (that's `test_router.py::test_shadow_sampling_*`'s job) -- without
pinning it, `router_policy.yaml`'s `dev` stage rate of `1.0` would upgrade
every single `fast` verdict below to `shadow` and fail every one of them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from iam_sentinel_agents.tools.common.router import RequestRouter, RouterRequest

pytestmark = pytest.mark.unit

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "evals" / "router" / "golden.jsonl"

_REQUIRED_FIELDS = {
    "id",
    "category",
    "notes",
    "request",
    "expected_mode",
    "expected_dispatch_target",
    "expected_rule_id",
}
_VALID_MODES = {"fast", "slow", "shadow"}


def _load_golden() -> list[dict[str, Any]]:
    lines = GOLDEN_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_golden_file_has_at_least_thirty_entries() -> None:
    entries = _load_golden()
    assert len(entries) >= 30


def test_every_entry_has_the_required_fields_and_a_valid_mode() -> None:
    for entry in _load_golden():
        missing = _REQUIRED_FIELDS - entry.keys()
        assert not missing, f"{entry.get('id')} missing {missing}"
        assert entry["expected_mode"] in _VALID_MODES, entry


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_golden()]
    assert len(ids) == len(set(ids))


def test_router_classifies_every_golden_case_correctly() -> None:
    router = RequestRouter(rng=lambda: 1.0)
    failures: list[str] = []
    for entry in _load_golden():
        request = RouterRequest.model_validate({**entry["request"], "correlation_id": entry["id"]})
        decision = router.classify(request)
        if decision.mode != entry["expected_mode"] or (
            decision.dispatch_target != entry["expected_dispatch_target"]
        ):
            failures.append(
                f"{entry['id']}: expected mode={entry['expected_mode']!r} "
                f"target={entry['expected_dispatch_target']!r}, got "
                f"mode={decision.mode!r} target={decision.dispatch_target!r}"
            )
        if decision.matched_policy_rule_id != entry["expected_rule_id"]:
            failures.append(
                f"{entry['id']}: expected rule={entry['expected_rule_id']!r}, "
                f"got rule={decision.matched_policy_rule_id!r}"
            )
    assert not failures, "\n".join(failures)
