"""Acceptance gates for phase-00 (aws-infra README §7-8): `cdk synth` succeeds
for every stage, `cdk-nag` reports zero AwsSolutions errors, and every
stack's synthesized template is snapshot-stable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aws_cdk import Aspects
from aws_cdk.assertions import Annotations, Match, Template
from cdk_nag import AwsSolutionsChecks

from iam_sentinel_infra.app_factory import build_app

_STAGES = ["dev", "staging", "prod"]
_STACK_IDS = [
    "SentinelSecurity",
    "SentinelFoundation",
    "SentinelAthena",
    "SentinelLambda",
    "SentinelBedrock",
    "SentinelEvent",
    "SentinelApi",
    "SentinelCrossAccount",
]

SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__"


@pytest.mark.parametrize("stage", _STAGES)
def test_synth_succeeds_for_every_stage(stage: str) -> None:
    app = build_app(stage)
    assembly = app.synth()
    assert {stack_id for stack_id in _STACK_IDS} == {
        artifact.id for artifact in assembly.stacks
    }


def test_cdk_nag_reports_zero_errors() -> None:
    app = build_app("dev")
    Aspects.of(app).add(AwsSolutionsChecks())

    for stack_id in _STACK_IDS:
        stack = app.node.find_child(stack_id)
        errors = Annotations.from_stack(stack).find_error(
            "*", Match.string_like_regexp("AwsSolutions-.*")
        )
        assert errors == []


@pytest.mark.parametrize("stack_id", _STACK_IDS)
def test_stack_template_snapshot_is_stable(stack_id: str) -> None:
    app = build_app("dev")
    stack = app.node.find_child(stack_id)
    template = Template.from_stack(stack).to_json()

    snapshot_path = SNAPSHOT_DIR / f"{stack_id}.json"
    if not snapshot_path.exists():
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(template, indent=2, sort_keys=True), encoding="utf-8")
        pytest.skip(f"wrote initial snapshot for {stack_id}; re-run to verify stability")

    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert template == expected
