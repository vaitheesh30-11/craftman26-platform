"""Loads `prime_supervisor.txt` and detects drift at cold start (phase-01
§9 risk: "prompt drift over time (model updates or human edits)... prompt
file is checksummed on Lambda cold start; drift raises an alarm").

`PRIME_PROMPT_SHA256` is the pinned, reviewed checksum. A mismatch means
someone edited the prompt file without also updating this constant (or the
file was corrupted/tampered) -- either way, Prime must not silently run
with an unreviewed instruction, so `load_prime_prompt` raises rather than
logging-and-continuing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from iam_sentinel_agents.errors import SentinelAgentError

_PROMPT_PATH = Path(__file__).parent / "prime_supervisor.txt"

# Pinned at authoring time. Bump deliberately (in the same commit as the
# prompt edit) whenever `prime_supervisor.txt` legitimately changes.
PRIME_PROMPT_SHA256 = "32b6b034a6c645b5fb46b9d186960ddd2e4d49bbc6720bf25007d3085c8b1ab0"


class PromptDriftError(SentinelAgentError):
    """Raised when `prime_supervisor.txt`'s checksum no longer matches
    `PRIME_PROMPT_SHA256` -- an unreviewed edit or corrupted deploy artifact.
    """


def prime_prompt_checksum() -> str:
    return hashlib.sha256(_PROMPT_PATH.read_bytes()).hexdigest()


def load_prime_prompt(*, verify_checksum: bool = True) -> str:
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    if verify_checksum:
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual != PRIME_PROMPT_SHA256:
            raise PromptDriftError(
                f"prime_supervisor.txt checksum drift: expected {PRIME_PROMPT_SHA256!r}, "
                f"got {actual!r}"
            )
    return text
