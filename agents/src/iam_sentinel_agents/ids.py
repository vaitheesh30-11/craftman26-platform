"""ULID generation (Crockford base32, 48-bit ms timestamp + 80-bit random).

No `ulid` package is vendored anywhere in this repo (the dependency lists
for agents/adapters carry no such entry) -- every contract only ever
*validates* a ULID against `ULID_PATTERN`. Prime's post-turn processing is
the first caller that must *mint* one (`DecisionRecord.decision_id`), so
this is a minimal, dependency-free implementation of the published ULID
spec (https://github.com/ulid/spec) rather than adding a new third-party
dependency for 20 lines of well-defined bit-shuffling.
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
