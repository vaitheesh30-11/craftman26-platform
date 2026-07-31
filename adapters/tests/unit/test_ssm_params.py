from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_adapters.ssm.params import SsmParameterClient


class _ParameterNotFound(Exception):
    pass


def test_get_parameter_returns_value_when_present() -> None:
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": "arn:aws:states:...:stateMachine:X"}
    }
    client = SsmParameterClient(ssm_client=mock_ssm)

    value = client.get_parameter("/sentinel/dev/approval/state-machine-arn")

    assert value == "arn:aws:states:...:stateMachine:X"


def test_get_parameter_returns_none_when_not_found_instead_of_raising() -> None:
    mock_ssm = MagicMock()
    mock_ssm.exceptions.ParameterNotFound = _ParameterNotFound
    mock_ssm.get_parameter.side_effect = _ParameterNotFound()
    client = SsmParameterClient(ssm_client=mock_ssm)

    value = client.get_parameter("/sentinel/dev/approval/state-machine-arn")

    assert value is None


def test_get_parameter_caches_and_does_not_re_call_ssm() -> None:
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "cached-value"}}
    client = SsmParameterClient(ssm_client=mock_ssm)

    client.get_parameter("/sentinel/dev/x")
    client.get_parameter("/sentinel/dev/x")

    mock_ssm.get_parameter.assert_called_once()
