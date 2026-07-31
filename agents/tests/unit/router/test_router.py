"""`RequestRouter`/`load_policy` -- policy loading (bundled YAML + SSM
hot-swap override, agents phase-15 §4/§6 Step 1), and the shadow-sampling
overlay (§4's coin-flip row, §10's HIGH+ severity 100%-for-30-days
mitigation). The decision-tree correctness itself is the golden set's job
(`test_router_golden.py`); this file covers the plumbing around it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.tools.common.router import (
    load_policy,
    RequestRouter,
    RouterRequest,
)

pytestmark = pytest.mark.unit


def test_load_policy_reads_the_bundled_yaml_by_default() -> None:
    policy = load_policy()
    assert policy.fast_path_routes["/analyze/passrole"].target == "F1"
    assert "why" in policy.reasoning_keywords


def test_load_policy_prefers_the_ssm_published_override() -> None:
    override_yaml = """
version: 1
fast_path_routes:
  /analyze/passrole:
    target: F1
    required_fields: []
reasoning_keywords: [banana]
narrative_hint_key: include_narrative
multi_feature_threshold: 5
shadow_sampling_rate:
  dev: 0.0
high_severity_shadow_rate: 1.0
router_change_window_days: 0
"""
    ssm = MagicMock()
    ssm.get_parameter.return_value = override_yaml
    policy = load_policy(ssm_client=ssm)
    ssm.get_parameter.assert_called_once_with("/sentinel/router/policy")
    assert policy.reasoning_keywords == ["banana"]
    assert policy.multi_feature_threshold == 5


def test_load_policy_falls_back_to_bundled_yaml_when_no_param_published() -> None:
    ssm = MagicMock()
    ssm.get_parameter.return_value = None
    policy = load_policy(ssm_client=ssm)
    assert policy.fast_path_routes["/scan/slr-breakage"].target == "F8"


def _fast_request(**overrides: object) -> RouterRequest:
    base: dict[str, object] = {
        "correlation_id": "corr-1",
        "api_path": "/analyze/passrole",
        "query_text": None,
        "hints": {},
        "fields_present": ["account_id"],
        "features_touched": [],
    }
    base.update(overrides)
    return RouterRequest.model_validate(base)


def test_shadow_sampling_never_fires_when_rng_exceeds_the_rate() -> None:
    router = RequestRouter(stage="prod", rng=lambda: 0.5)
    decision = router.classify(_fast_request())
    assert decision.mode == "fast"


def test_shadow_sampling_fires_when_rng_is_below_the_rate() -> None:
    router = RequestRouter(stage="dev", rng=lambda: 0.0)
    decision = router.classify(_fast_request())
    assert decision.mode == "shadow"
    assert decision.fallback_target == "F1"
    assert decision.matched_policy_rule_id == "R7-shadow-sample"


def test_shadow_sampling_only_overlays_an_otherwise_fast_decision() -> None:
    router = RequestRouter(stage="dev", rng=lambda: 0.0)
    decision = router.classify(_fast_request(api_path="/agent/chat", query_text="hello"))
    assert decision.mode == "slow"


def test_high_severity_hint_within_change_window_uses_the_100pct_rate() -> None:
    router = RequestRouter(
        stage="prod", rng=lambda: 0.5, is_within_change_window=True
    )
    decision = router.classify(_fast_request(min_severity_hint="HIGH"))
    assert decision.mode == "shadow"


def test_low_severity_hint_within_change_window_uses_the_normal_prod_rate() -> None:
    router = RequestRouter(
        stage="prod", rng=lambda: 0.5, is_within_change_window=True
    )
    decision = router.classify(_fast_request(min_severity_hint="LOW"))
    assert decision.mode == "fast"
