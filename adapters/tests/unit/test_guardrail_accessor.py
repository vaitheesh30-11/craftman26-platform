from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_adapters.llm.guardrail import GuardrailAccessor
from iam_sentinel_adapters.settings import settings


def test_guardrail_id_reads_the_stage_scoped_param() -> None:
    fake_ssm = MagicMock()
    fake_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-123"}}
    accessor = GuardrailAccessor(client=fake_ssm)

    assert accessor.guardrail_id() == "gr-123"
    fake_ssm.get_parameter.assert_called_once_with(Name=f"/sentinel/{settings.stage}/guardrail/id")


def test_guardrail_version_is_cached_across_calls() -> None:
    fake_ssm = MagicMock()
    fake_ssm.get_parameter.return_value = {"Parameter": {"Value": "3"}}
    accessor = GuardrailAccessor(client=fake_ssm)

    first = accessor.guardrail_version()
    second = accessor.guardrail_version()

    assert first == second == "3"
    fake_ssm.get_parameter.assert_called_once()
