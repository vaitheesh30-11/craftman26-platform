"""agents phase-11 §3: the Guardrail's policy content (config/guardrail_v1.json)
is valid JSON with the fields SecurityStack pops off / forwards."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "guardrail_v1.json"


def test_guardrail_policy_config_is_valid_json_with_required_fields() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert "blockedInputMessaging" in config
    assert "blockedOutputsMessaging" in config
    assert "topicPolicyConfig" in config
    assert "contentPolicyConfig" in config
    assert "sensitiveInformationPolicyConfig" in config
    assert "contextualGroundingPolicyConfig" in config


def test_account_id_regex_anonymizes_rather_than_blocks() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    regexes = config["sensitiveInformationPolicyConfig"]["regexesConfig"]
    account_id_rule = next(r for r in regexes if r["name"] == "AwsAccountId")

    assert account_id_rule["action"] == "ANONYMIZE"
