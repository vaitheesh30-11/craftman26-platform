"""Opaque `next_token` codec (backend phase-01 §6): a base64 encoding of
DDB's own `LastEvaluatedKey`, so backend never has to invent its own cursor
scheme -- the key a page ended on IS the cursor for the next one.
"""

from __future__ import annotations

import base64
import json
from typing import Any

MAX_LIMIT = 100


class InvalidNextTokenError(ValueError):
    """Raised when a caller-supplied `next_token` doesn't decode cleanly."""


def encode_next_token(last_evaluated_key: dict[str, Any] | None) -> str | None:
    if last_evaluated_key is None:
        return None
    raw = json.dumps(last_evaluated_key, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_next_token(next_token: str | None) -> dict[str, Any] | None:
    if not next_token:
        return None
    try:
        raw = base64.urlsafe_b64decode(next_token.encode("ascii"))
        decoded = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidNextTokenError(f"malformed next_token: {exc}") from exc
    if not isinstance(decoded, dict):
        raise InvalidNextTokenError("next_token did not decode to an object")
    return decoded


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))
