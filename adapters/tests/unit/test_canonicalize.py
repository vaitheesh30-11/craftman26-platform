from __future__ import annotations

from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json


def test_keys_are_sorted() -> None:
    assert canonicalize_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_output_has_no_extraneous_whitespace() -> None:
    result = canonicalize_json({"a": [1, 2, 3]})
    assert " " not in result


def test_deterministic_regardless_of_input_key_order() -> None:
    assert canonicalize_json({"x": 1, "y": 2}) == canonicalize_json({"y": 2, "x": 1})
