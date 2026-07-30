from __future__ import annotations

import pytest

from iam_sentinel_agents.prompts.registry import (
    load_prime_prompt,
    prime_prompt_checksum,
    PRIME_PROMPT_SHA256,
    PromptDriftError,
)


def test_pinned_checksum_matches_the_file_on_disk() -> None:
    assert prime_prompt_checksum() == PRIME_PROMPT_SHA256


def test_load_prime_prompt_returns_the_full_text() -> None:
    text = load_prime_prompt()
    assert "Sentinel Prime" in text
    assert "ROUTING HEURISTICS" in text


def test_load_prime_prompt_raises_on_checksum_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("iam_sentinel_agents.prompts.registry.PRIME_PROMPT_SHA256", "0" * 64)

    with pytest.raises(PromptDriftError):
        load_prime_prompt()

    load_prime_prompt(verify_checksum=False)  # must not raise
