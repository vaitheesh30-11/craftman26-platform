from __future__ import annotations

import pytest

from iam_sentinel_agents.errors import ContractError
from iam_sentinel_agents.prime.result_parser import parse_prime_completion

_VALID_COMPLETION = """
PROGRESS: Routing to passrole-cartographer.
PROGRESS: Aggregating findings.
RESULT:
```json
{
  "status": "ANSWERED",
  "narrative": "Found 1 CRITICAL PassRole finding.",
  "findings": [],
  "remediations_proposed": [],
  "specialist_calls": [{"collaborator": "passrole-cartographer", "duration_ms": 1200}]
}
```
"""


def test_parses_progress_lines_and_result_block() -> None:
    parsed = parse_prime_completion(_VALID_COMPLETION)

    assert parsed.progress_lines == [
        "Routing to passrole-cartographer.",
        "Aggregating findings.",
    ]
    assert parsed.result["status"] == "ANSWERED"
    assert parsed.result["specialist_calls"][0]["collaborator"] == "passrole-cartographer"


def test_raises_when_no_result_block_present() -> None:
    with pytest.raises(ContractError, match="RESULT"):
        parse_prime_completion("PROGRESS: still thinking.")


def test_raises_on_malformed_json_in_result_block() -> None:
    broken = 'RESULT:\n```json\n{"status": "ANSWERED",}\n```\n'
    with pytest.raises(ContractError, match="not valid JSON"):
        parse_prime_completion(broken)


def test_raises_when_a_required_key_is_missing() -> None:
    incomplete = 'RESULT:\n```json\n{"status": "ANSWERED"}\n```\n'
    with pytest.raises(ContractError, match="missing required keys"):
        parse_prime_completion(incomplete)
