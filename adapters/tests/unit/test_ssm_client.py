from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_adapters.ssm.client import SsmClient


class _ParameterNotFound(Exception):
    pass


def test_get_string_list_splits_and_strips_comma_separated_value() -> None:
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "role/a, role/b ,role/c"}}
    client = SsmClient(client=mock_ssm)

    values = client.get_string_list("/sentinel/never-revoke-role-patterns")

    assert values == ["role/a", "role/b", "role/c"]


def test_get_string_list_returns_default_when_parameter_not_found() -> None:
    mock_ssm = MagicMock()
    mock_ssm.exceptions.ParameterNotFound = _ParameterNotFound
    mock_ssm.get_parameter.side_effect = _ParameterNotFound()
    client = SsmClient(client=mock_ssm)

    values = client.get_string_list("/sentinel/missing", default=["fallback"])

    assert values == ["fallback"]


def test_get_string_list_returns_empty_list_when_not_found_and_no_default() -> None:
    mock_ssm = MagicMock()
    mock_ssm.exceptions.ParameterNotFound = _ParameterNotFound
    mock_ssm.get_parameter.side_effect = _ParameterNotFound()
    client = SsmClient(client=mock_ssm)

    assert client.get_string_list("/sentinel/missing") == []
