"""RFC 8785 JSON Canonicalization Scheme (JCS).

Produces the exact deterministic byte representation RFC 8785 requires:
UTF-8, recursively key-sorted objects, no insignificant whitespace, and
ECMA-262 `Number::toString` formatting for every number. Used both to
fence `trusted_input` into a prompt (adapters phase-03 §4) and to
canonicalize evidence payloads before KMS signing (phase-04 §4).

Verified against the reference test vectors published at
https://github.com/cyberphone/json-canonicalization (values.json,
structures.json, arrays.json, french.json) — see
adapters/tests/unit/test_canonicalize.py.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any


def canonicalize_json(value: Any) -> str:
    return _encode(value)


def _encode(value: Any) -> str:  # noqa: PLR0911 -- flat type dispatch, splitting hurts readability
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _encode_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list | tuple):
        return _encode_array(value)
    if isinstance(value, dict):
        return _encode_object(value)
    raise TypeError(f"cannot canonicalize value of type {type(value)!r}")


def _encode_array(value: list[Any] | tuple[Any, ...]) -> str:
    return "[" + ",".join(_encode(item) for item in value) + "]"


def _encode_object(value: dict[Any, Any]) -> str:
    items = sorted(value.items(), key=lambda kv: kv[0])
    pairs = (f"{json.dumps(k, ensure_ascii=False)}:{_encode(v)}" for k, v in items)
    return "{" + ",".join(pairs) + "}"


# ECMA-262 Number::toString's fixed-vs-exponential-notation thresholds.
_MAX_FIXED_NOTATION_EXPONENT = 21
_MIN_FIXED_NOTATION_EXPONENT = -6


def _encode_number(value: float) -> str:
    if math.isnan(value):
        raise ValueError("NaN is not a valid JSON number")
    if math.isinf(value):
        raise ValueError("Infinity is not a valid JSON number")
    if value == 0.0:
        return "0"

    negative = value < 0
    magnitude = -value if negative else value
    digits, exponent = _shortest_digits_and_exponent(magnitude)
    k = len(digits)
    n = exponent + k

    if k <= n <= _MAX_FIXED_NOTATION_EXPONENT:
        body = digits + "0" * (n - k)
    elif 0 < n <= _MAX_FIXED_NOTATION_EXPONENT:
        body = digits[:n] + "." + digits[n:]
    elif _MIN_FIXED_NOTATION_EXPONENT < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mantissa = digits[0] + ("." + digits[1:] if k > 1 else "")
        body = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"

    return f"-{body}" if negative else body


def _shortest_digits_and_exponent(magnitude: float) -> tuple[str, int]:
    """Python's `repr` gives the shortest round-tripping decimal digits for
    a double -- the same mathematical quantity ECMA-262 requires -- but its
    own formatting conventions (always showing `.0` for integral values)
    differ from ECMA's, so the digit/exponent pair is extracted here and
    reformatted by the caller.
    """
    repr_str = repr(magnitude)
    if "e" not in repr_str and "E" not in repr_str and repr_str.endswith(".0"):
        repr_str = repr_str[:-2]

    decimal_value = Decimal(repr_str)
    _sign, digit_tuple, exponent = decimal_value.as_tuple()
    digits = "".join(str(d) for d in digit_tuple)
    return digits, int(exponent)
