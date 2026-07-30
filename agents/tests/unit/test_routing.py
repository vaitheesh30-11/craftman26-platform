from __future__ import annotations

import pytest

from iam_sentinel_agents.prime.routing import (
    MAX_PARALLEL_COLLABORATORS,
    parse_routing_heuristics,
    route,
    RoutingTableError,
)
from iam_sentinel_agents.prompts.registry import load_prime_prompt

_PROMPT = load_prime_prompt()


def test_parses_all_eight_feature_ids_from_the_real_prompt() -> None:
    heuristics = parse_routing_heuristics(_PROMPT)
    assert set(heuristics) == {"F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"}


def test_route_matches_passrole_query_to_f1() -> None:
    assert route("who can PassRole to this admin role?") == ["F1"]


def test_route_returns_nothing_for_an_unrelated_query() -> None:
    assert route("what's the weather like today?") == []


def test_route_caps_fan_out_at_max_parallel() -> None:
    # every heuristic phrase in one query -- should still return no more
    # than the parallel-invocation cap the prompt itself enforces.
    heuristics = parse_routing_heuristics(_PROMPT)
    everything = " ".join(phrase for phrases in heuristics.values() for phrase in phrases)

    assert len(route(everything)) <= MAX_PARALLEL_COLLABORATORS


def test_parse_routing_heuristics_rejects_a_malformed_section() -> None:
    broken = "ROUTING HEURISTICS\n- not a valid line\nOUTPUT PROTOCOL"
    with pytest.raises(RoutingTableError):
        parse_routing_heuristics(broken)
