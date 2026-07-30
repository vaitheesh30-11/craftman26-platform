from __future__ import annotations

import re

from iam_sentinel_agents.contracts.common import ULID_PATTERN
from iam_sentinel_agents.ids import new_ulid


def test_new_ulid_matches_the_contract_pattern() -> None:
    for _ in range(20):
        assert re.match(ULID_PATTERN, new_ulid())


def test_new_ulid_is_unique_across_calls() -> None:
    ulids = {new_ulid() for _ in range(100)}
    assert len(ulids) == 100
