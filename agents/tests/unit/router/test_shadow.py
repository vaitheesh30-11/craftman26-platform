"""Shadow-mode divergence detection (agents phase-15 §6 Step 3, §8 Test
Plan: "5 curated cases where fast and slow paths should agree (identical);
3 where fast should escalate to slow"). The 3 escalation cases live in
`test_fast_path.py` (`AmbiguityError`, §8's other test-plan line item) --
this file owns divergence *classification* once both outputs exist.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from typing import Any
from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.tools.common.shadow import (
    build_diff_summary,
    compute_divergence_kind,
    run_shadow,
)

pytestmark = pytest.mark.unit


def _output(**overrides: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "verdict": "CONFIRM",
        "reason": "1 PassRole grant found",
        "findings": [{"from_principal": "arn:aws:iam::111122223333:user/Deployer"}],
        "remediation": None,
    }
    base.update(overrides)
    return base


# 5 curated "agree" cases -- identical or narrative-only differences.
@pytest.mark.parametrize(
    "fast,slow",
    [
        (_output(), _output()),
        (_output(reason="1 PassRole grant found"), _output(reason="one grant was found")),
        (_output(reason="a"), _output(reason="b", findings=_output()["findings"])),
        (_output(verdict="REJECT", findings=[]), _output(verdict="REJECT", findings=[], reason="none")),
        (
            _output(remediation={"safe_scp": {"a": 1}}),
            _output(remediation={"safe_scp": {"a": 1}}, reason="different narrative"),
        ),
    ],
)
def test_five_curated_cases_agree(fast: dict[str, Any], slow: dict[str, Any]) -> None:
    kind = compute_divergence_kind(fast, slow)
    assert kind in ("identical", "semantic_match")


def test_identical_outputs_are_identical() -> None:
    assert compute_divergence_kind(_output(), _output()) == "identical"


def test_different_verdict_is_material_disagreement() -> None:
    kind = compute_divergence_kind(_output(verdict="CONFIRM"), _output(verdict="REJECT"))
    assert kind == "material_disagreement"


def test_different_remediation_is_material_disagreement() -> None:
    kind = compute_divergence_kind(
        _output(remediation=None), _output(remediation={"safe_scp": {}})
    )
    assert kind == "material_disagreement"


def test_different_finding_ids_is_material_disagreement() -> None:
    kind = compute_divergence_kind(
        _output(findings=[{"a": 1}]), _output(findings=[{"a": 2}])
    )
    assert kind == "material_disagreement"


def test_build_diff_summary_lists_the_differing_fields() -> None:
    summary = build_diff_summary(_output(verdict="CONFIRM"), _output(verdict="REJECT"))
    assert "verdict" in summary


def test_build_diff_summary_reports_no_differences() -> None:
    assert build_diff_summary(_output(), _output()) == "no field-level differences"


def test_run_shadow_persists_a_divergence_record_and_returns_the_first_result() -> None:
    async def _fast() -> dict[str, Any]:
        return _output(verdict="REJECT", findings=[])

    async def _slow() -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return _output(verdict="CONFIRM")

    divergence_client = MagicMock()

    body, record = asyncio.run(
        run_shadow(
            correlation_id="c1",
            feature_id="F1",
            input_payload={"account_id": "123456789012"},
            fast_runner=_fast,
            slow_runner=_slow,
            divergence_client=divergence_client,
            now=datetime(2026, 7, 31, tzinfo=UTC),
        )
    )

    assert body["verdict"] == "REJECT"
    assert record.divergence_kind == "material_disagreement"
    assert record.reviewed is False
    divergence_client.put.assert_called_once()
    put_arg = divergence_client.put.call_args[0][0]
    assert put_arg["correlation_id"] == "c1"
    assert put_arg["feature_id"] == "F1"


def test_run_shadow_marks_identical_results_as_already_reviewed() -> None:
    async def _same() -> dict[str, Any]:
        return _output()

    _body, record = asyncio.run(
        run_shadow(
            correlation_id="c2",
            feature_id="F7",
            input_payload={},
            fast_runner=_same,
            slow_runner=_same,
        )
    )
    assert record.divergence_kind == "identical"
    assert record.reviewed is True
