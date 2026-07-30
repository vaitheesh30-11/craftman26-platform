"""Prime's instruction prompt + drift detection (phase-01 §5, §9 risk)."""

from __future__ import annotations

from iam_sentinel_agents.prompts.registry import (
    load_prime_prompt,
    prime_prompt_checksum,
    PRIME_PROMPT_SHA256,
    PromptDriftError,
)

__all__ = [
    "PRIME_PROMPT_SHA256",
    "PromptDriftError",
    "load_prime_prompt",
    "prime_prompt_checksum",
]
