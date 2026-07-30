"""Composes `<trusted_input>` + `<untrusted_context>` fenced prompts so
every model this platform calls treats untrusted content as data, never
instructions (phase-03 §4; SYSTEM_STATE.md §2 rule 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from iam_sentinel_adapters.errors import PromptTooLargeError, ValidationError
from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json
from iam_sentinel_adapters.prompts.sanitizer import sanitize_untrusted

_BLOCK_TYPE_PATTERN = re.compile(r"^[a-z_]{1,64}$")
_MAX_PROMPT_LENGTH = 32_768


@dataclass(frozen=True)
class UntrustedBlock:
    type: str
    body: str


def build_prompt(
    trusted_input: dict[str, object],
    blocks: list[UntrustedBlock],
    *,
    max_block_length: int = 4096,
) -> str:
    parts = [f"<trusted_input>\n{canonicalize_json(trusted_input)}\n</trusted_input>"]

    for block in blocks:
        if not _BLOCK_TYPE_PATTERN.match(block.type):
            raise ValidationError(
                f"untrusted block type {block.type!r} does not match ^[a-z_]{{1,64}}$"
            )
        sanitized_body = sanitize_untrusted(block.body, max_length=max_block_length)
        parts.append(f'<untrusted_context type="{block.type}">\n{sanitized_body}\n</untrusted_context>')

    prompt = "\n".join(parts)
    if len(prompt) > _MAX_PROMPT_LENGTH:
        raise PromptTooLargeError(
            f"composed prompt is {len(prompt)} chars, exceeds the {_MAX_PROMPT_LENGTH}-char cap"
        )

    return prompt
