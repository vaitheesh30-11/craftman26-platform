"""Parses Prime's OUTPUT PROTOCOL (phase-01 §5): zero or more `PROGRESS:`
lines followed by one `RESULT:` fenced JSON block. Bedrock's `InvokeAgent`
returns the model's raw completion text; this is the boundary that turns
it into something `decision_composer` and the backend's WebSocket relay
can consume without either one re-parsing prose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from iam_sentinel_agents.errors import ContractError

_PROGRESS_LINE = re.compile(r"^PROGRESS:\s*(.+)$", re.MULTILINE)
_RESULT_BLOCK = re.compile(r"RESULT:\s*```json\s*(?P<body>\{.*?\})\s*```", re.DOTALL)


@dataclass(frozen=True)
class ParsedPrimeTurn:
    progress_lines: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)


_REQUIRED_RESULT_KEYS = (
    "status",
    "narrative",
    "findings",
    "remediations_proposed",
    "specialist_calls",
)


def parse_prime_completion(completion_text: str) -> ParsedPrimeTurn:
    progress_lines = [m.group(1).strip() for m in _PROGRESS_LINE.finditer(completion_text)]

    match = _RESULT_BLOCK.search(completion_text)
    if match is None:
        raise ContractError("Prime completion has no RESULT: ```json ... ``` block")

    try:
        result = json.loads(match.group("body"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"Prime RESULT block is not valid JSON: {exc}") from exc

    missing = [key for key in _REQUIRED_RESULT_KEYS if key not in result]
    if missing:
        raise ContractError(f"Prime RESULT block missing required keys: {missing}")

    return ParsedPrimeTurn(progress_lines=progress_lines, result=result)
