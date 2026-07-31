from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f7.plain_english import build_plain_english

pytestmark = pytest.mark.unit

_KWARGS = {
    "action": "ec2:RunInstances",
    "denying_scp_name": "RootDenyRunInstances",
    "denying_level": "root",
    "denying_statement_id": "DenyRunInstances",
    "allowing_scp_name": "OuAllowRunInstances",
    "allowing_level": "ou",
}


def test_matches_spec_template_verbatim() -> None:
    text = build_plain_english(**_KWARGS)
    assert text == (
        "SCP RootDenyRunInstances at root level denies ec2:RunInstances "
        "because of statement DenyRunInstances. SCP OuAllowRunInstances "
        "at ou level allows ec2:RunInstances. Under AWS SCP evaluation "
        "rules, an explicit Deny at ANY level overrides an Allow at any other "
        "level, so ec2:RunInstances is DENIED in this account."
    )


def test_deterministic_across_repeated_calls() -> None:
    assert build_plain_english(**_KWARGS) == build_plain_english(**_KWARGS)


def test_missing_statement_id_falls_back_to_placeholder() -> None:
    kwargs = dict(_KWARGS, denying_statement_id=None)
    text = build_plain_english(**kwargs)
    assert "<unnamed statement>" in text
