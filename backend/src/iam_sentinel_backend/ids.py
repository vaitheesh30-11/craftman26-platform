"""ULID generation (Crockford base32, 48-bit ms timestamp + 80-bit random).

Deliberately duplicated from `agents.ids` rather than imported: `backend/`
does not depend on `agents/` (module boundary -- backend talks to Prime
only through Bedrock's `InvokeAgent` API via the adapters LLM interface,
never by importing agents' Python package), and this is 20 lines of
well-defined, dependency-free bit-shuffling per the published ULID spec
(https://github.com/ulid/spec), not shared business logic worth a new
cross-module edge for.
"""

from __future__ import annotations

import os
import time

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIMESTAMP_BITS = 48
_RANDOM_BYTES = 10  # 80 bits


def new_ulid() -> str:
    timestamp_ms = int(time.time() * 1000)
    if timestamp_ms >= 1 << _TIMESTAMP_BITS:
        raise ValueError("timestamp exceeds ULID's 48-bit budget (year ~10889)")

    value = timestamp_ms << 80
    value |= int.from_bytes(os.urandom(_RANDOM_BYTES), byteorder="big")

    chars: list[str] = []
    for _ in range(26):
        chars.append(_CROCKFORD_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))
