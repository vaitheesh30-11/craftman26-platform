"""`@memoize_procedural` hit/miss/TTL-expire paths (phase-14 §7 Test Plan)."""

from __future__ import annotations

import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.common.memoize import compute_pattern_hash, memoize_procedural
from tests.unit.memory import _ddb

pytestmark = pytest.mark.unit


@mock_aws
def test_second_call_with_same_args_is_a_cache_hit_not_a_recompute() -> None:
    memory = _ddb.memory_client()
    calls = []

    @memoize_procedural("scp_effective_policy", ttl_seconds=900, memory=memory)
    def compute(x: int) -> dict[str, int]:
        calls.append(x)
        return {"value": x * 2}

    first = compute(21)
    second = compute(21)

    assert first == {"value": 42}
    assert second == {"value": 42}
    assert calls == [21]  # only computed once


@mock_aws
def test_different_args_are_a_cache_miss() -> None:
    memory = _ddb.memory_client()
    calls = []

    @memoize_procedural("scp_effective_policy", ttl_seconds=900, memory=memory)
    def compute(x: int) -> dict[str, int]:
        calls.append(x)
        return {"value": x}

    compute(1)
    compute(2)

    assert calls == [1, 2]


@mock_aws
def test_expired_entry_is_recomputed() -> None:
    memory = _ddb.memory_client()
    calls = []

    @memoize_procedural("scp_effective_policy", ttl_seconds=900, memory=memory)
    def compute(x: int) -> dict[str, int]:
        calls.append(x)
        return {"value": x}

    compute(1)  # populates the cache with a live (900s) TTL
    assert calls == [1]

    # Simulate TTL expiry without depending on wall-clock time: overwrite
    # the same pattern_hash's entry with a negative TTL (DDB TTL deletion
    # is itself best-effort/async, so `_is_expired`'s client-side check --
    # not the presence of the row -- is what this test exercises).
    pattern_hash = compute_pattern_hash(version="v1", args=(1,), kwargs={})
    memory.procedural_put(
        "scp_effective_policy", pattern_hash, {"value": 1}, ttl_seconds=-10
    )

    compute(1)

    assert calls == [1, 1]  # recomputed after expiry


@mock_aws
def test_version_bump_invalidates_previously_cached_pattern_hash() -> None:
    """phase-14 §9 risk mitigation: pattern_hash folds in the code/engine
    version so a code change can't silently reuse a stale cached result.
    """
    memory = _ddb.memory_client()

    @memoize_procedural("scp_effective_policy", ttl_seconds=900, memory=memory, version="v1")
    def compute_v1(x: int) -> dict[str, int]:
        return {"value": x}

    @memoize_procedural("scp_effective_policy", ttl_seconds=900, memory=memory, version="v2")
    def compute_v2(x: int) -> dict[str, int]:
        return {"value": x * 100}

    compute_v1(5)
    result = compute_v2(5)

    assert result == {"value": 500}  # not served from v1's cache entry


def test_compute_pattern_hash_is_deterministic_and_order_independent_for_kwargs() -> None:
    hash_a = compute_pattern_hash(version="v1", args=(), kwargs={"a": 1, "b": 2})
    hash_b = compute_pattern_hash(version="v1", args=(), kwargs={"b": 2, "a": 1})
    hash_c = compute_pattern_hash(version="v2", args=(), kwargs={"a": 1, "b": 2})

    assert hash_a == hash_b
    assert hash_a != hash_c
