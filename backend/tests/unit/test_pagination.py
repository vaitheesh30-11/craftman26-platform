from __future__ import annotations

import base64
import json

import pytest

from iam_sentinel_backend.pagination import (
    clamp_limit,
    decode_next_token,
    encode_next_token,
    InvalidNextTokenError,
)


def test_none_key_encodes_to_none_token() -> None:
    assert encode_next_token(None) is None


def test_round_trips_a_last_evaluated_key() -> None:
    key = {"account_id#feature_id": "111122223333#F1", "finding_id#detected_at": "abc#2026"}

    token = encode_next_token(key)
    assert token is not None
    assert decode_next_token(token) == key


def test_decode_none_or_empty_token_returns_none() -> None:
    assert decode_next_token(None) is None
    assert decode_next_token("") is None


def test_decode_malformed_token_raises() -> None:
    with pytest.raises(InvalidNextTokenError):
        decode_next_token("not-valid-base64!!!")


def test_decode_token_that_is_not_an_object_raises() -> None:
    token = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).decode()

    with pytest.raises(InvalidNextTokenError):
        decode_next_token(token)


def test_clamp_limit_bounds_between_one_and_max() -> None:
    assert clamp_limit(0) == 1
    assert clamp_limit(50) == 50
    assert clamp_limit(1000) == 100
