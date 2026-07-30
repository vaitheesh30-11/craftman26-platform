from __future__ import annotations

import pytest

from iam_sentinel_adapters.errors import PromptTooLargeError, ValidationError
from iam_sentinel_adapters.prompts.xml_fencer import UntrustedBlock, build_prompt


def test_build_prompt_is_deterministic_for_a_canonical_payload() -> None:
    trusted_input = {"b": 2, "a": 1}
    blocks = [UntrustedBlock(type="tag_value", body="prod-role")]

    first = build_prompt(trusted_input, blocks)
    second = build_prompt(trusted_input, blocks)

    assert first == second
    assert '<trusted_input>\n{"a":1,"b":2}\n</trusted_input>' in first
    assert '<untrusted_context type="tag_value">\nprod-role\n</untrusted_context>' in first


def test_multiple_blocks_are_composed_in_order() -> None:
    blocks = [
        UntrustedBlock(type="role_name", body="first"),
        UntrustedBlock(type="tag_value", body="second"),
    ]

    prompt = build_prompt({}, blocks)

    assert prompt.index("first") < prompt.index("second")


def test_invalid_block_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        build_prompt({}, [UntrustedBlock(type="Not-Valid!", body="x")])


def test_untrusted_body_is_sanitized() -> None:
    prompt = build_prompt({}, [UntrustedBlock(type="tag_value", body="<script>alert(1)</script>")])

    assert "<script>" not in prompt


def test_oversized_prompt_raises_prompt_too_large() -> None:
    huge_block = UntrustedBlock(type="tag_value", body="x" * 40_000)

    with pytest.raises(PromptTooLargeError):
        build_prompt({}, [huge_block], max_block_length=40_000)
