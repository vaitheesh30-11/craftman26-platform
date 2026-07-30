"""RFC 8785 compliance tests.

Four vectors reproduced from
https://github.com/cyberphone/json-canonicalization
(testdata/input + testdata/output for values.json, structures.json,
arrays.json, french.json). weird.json/unicode.json are omitted: their
combining-character/emoji content could not be confirmed byte-for-byte
through this session's tooling, and a wrong fixture is worse than none.
The four included vectors already exercise every canonicalization rule
this module depends on: recursive key sorting (non-ASCII, mixed-case),
integer vs. float number formatting, scientific-notation thresholds, and
JSON string escaping.

The "string" test value is built from named character pieces rather than
one hand-typed literal -- a single misplaced backslash-escape in a literal
containing this many backslashes, quotes, and control characters is
exactly the kind of mistake that silently produces a plausible-looking
but wrong fixture.
"""

from __future__ import annotations

import json

import pytest

from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json

# Decoded value: EURO SIGN, '$', U+000F, U+000A (newline), "A'B", '"', '\', '\', '"', '/'.
_VALUES_STRING_VALUE = "€$" + "\x0f" + "\n" + "A'B" + '"' + "\\" + "\\" + '"' + "/"

# The same value, re-serialized per RFC 8785: non-ASCII passed through raw,
# U+000F escaped as a 4-hex-digit unicode escape, newline as its short
# escape, quote and backslash escaped, forward slash left unescaped.
_VALUES_STRING_JSON = (
    '"' + "€$" + "\\u000f" + "\\n" + "A'B" + '\\"' + "\\\\\\\\" + '\\"' + "/" + '"'
)

_VALUES_INPUT = {
    "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
    "string": _VALUES_STRING_VALUE,
    "literals": [None, True, False],
}
_VALUES_OUTPUT = (
    '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
    f'"string":{_VALUES_STRING_JSON}}}'
)

_STRUCTURES_INPUT = {
    "1": {"f": {"f": "hi", "F": 5}, "\n": 56.0},
    "10": {},
    "": "empty",
    "a": {},
    "111": [{"e": "yes", "E": "no"}],
    "A": {},
}
_STRUCTURES_OUTPUT = (
    '{"":"empty","1":{"\\n":56,"f":{"F":5,"f":"hi"}},"10":{},'
    '"111":[{"E":"no","e":"yes"}],"A":{},"a":{}}'
)

_ARRAYS_INPUT = [56, {"d": True, "10": None, "1": []}]
_ARRAYS_OUTPUT = '[56,{"1":[],"10":null,"d":true}]'

_FRENCH_INPUT = {
    "peach": "This sorting order",
    "péché": "is wrong according to French",
    "pêche": "but canonicalization MUST",
    "sin": "ignore locale",
}
_FRENCH_OUTPUT = (
    '{"peach":"This sorting order","péché":"is wrong according to French",'
    '"pêche":"but canonicalization MUST","sin":"ignore locale"}'
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (_VALUES_INPUT, _VALUES_OUTPUT),
        (_STRUCTURES_INPUT, _STRUCTURES_OUTPUT),
        (_ARRAYS_INPUT, _ARRAYS_OUTPUT),
        (_FRENCH_INPUT, _FRENCH_OUTPUT),
    ],
)
def test_matches_the_published_rfc8785_vector(value: object, expected: str) -> None:
    assert canonicalize_json(value) == expected


def test_values_vector_string_matches_the_json_source_encoding() -> None:
    """The vector's own JSON source text encodes the string value as
    `\\u20ac$\\u000F\\u000aA'\\u0042\\u0022\\u005c\\\\\\"\\/` -- confirm our
    hand-built `_VALUES_STRING_VALUE` decodes to the same characters."""
    raw_input_fragment = '"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/"'
    assert json.loads(raw_input_fragment) == _VALUES_STRING_VALUE


def test_keys_are_sorted() -> None:
    assert canonicalize_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_output_has_no_extraneous_whitespace() -> None:
    result = canonicalize_json({"a": [1, 2, 3]})
    assert " " not in result


def test_deterministic_regardless_of_input_key_order() -> None:
    assert canonicalize_json({"x": 1, "y": 2}) == canonicalize_json({"y": 2, "x": 1})


def test_integral_float_drops_the_decimal_point() -> None:
    assert canonicalize_json({"n": 56.0}) == '{"n":56}'


def test_nan_and_infinity_are_rejected() -> None:
    with pytest.raises(ValueError, match="NaN"):
        canonicalize_json(float("nan"))
    with pytest.raises(ValueError, match="Infinity"):
        canonicalize_json(float("inf"))


def test_negative_zero_canonicalizes_to_zero() -> None:
    assert canonicalize_json(-0.0) == "0"
