"""Forged-content check on every model output (phase-01 §4 step 4):
defends against a model inventing an ARN or citation ID it was never
given, or echoing back a forbidden pattern that survived the sanitizer on
the way in.
"""

from __future__ import annotations

import re

from iam_sentinel_adapters.errors import ValidationError
from iam_sentinel_adapters.prompts.sanitizer import FORBIDDEN_PATTERNS

_ARN_PATTERN = re.compile(r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:[0-9]*:[^\s\"']+")
_EVIDENCE_ID_PATTERN = re.compile(r"\bevidence_id[\"']?\s*[:=]\s*[\"']?([a-zA-Z0-9_-]+)")


def validate_output(output_text: str, *, input_text: str, sanitized_input_set: set[str]) -> None:
    input_arns = set(_ARN_PATTERN.findall(input_text))
    for arn in _ARN_PATTERN.findall(output_text):
        if arn not in input_arns:
            raise ValidationError(f"output contains an ARN not present in the input: {arn!r}")

    for evidence_id in _EVIDENCE_ID_PATTERN.findall(output_text):
        if evidence_id not in sanitized_input_set:
            raise ValidationError(
                f"output cites evidence_id {evidence_id!r} not present in the sanitized input set"
            )

    for name, pattern in FORBIDDEN_PATTERNS.items():
        if pattern.search(output_text):
            raise ValidationError(f"output contains forbidden pattern {name!r}")
