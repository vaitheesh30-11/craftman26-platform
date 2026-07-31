"""Parses the prompt's own ROUTING HEURISTICS table instead of duplicating
it as a second, driftable Python data structure (phase-01 §5 line: "Include
the Collaborator directory verbatim so Prime doesn't need to be told again
per turn" -- the same single-source-of-truth spirit applies to the
heuristics a test or a pre-flight fan-out check needs to reason about
locally).

This module is NOT what routes a real turn -- Bedrock's SUPERVISOR
collaboration mode does that server-side, inside the deployed model, per
the prompt's own instructions (docs/decisions/0013). It exists so
(a) a unit test can assert the heuristics table is well-formed and stays
in sync with `contracts.common.FeatureID`, and (b) any pre-flight tooling
(e.g. a "which specialists would this touch" dry-run) has a keyword-match
approximation without an LLM call, capped at the same max-4-parallel fan-
out the prompt enforces (phase-01 §9 risk: Bedrock multi-agent parallel
invocation quotas).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from iam_sentinel_agents.errors import SentinelAgentError
from iam_sentinel_agents.prompts.registry import load_prime_prompt

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.common import FeatureID

MAX_PARALLEL_COLLABORATORS = 4

_SECTION_HEADER = "ROUTING HEURISTICS"
_NEXT_SECTION_HEADER = "OUTPUT PROTOCOL"
_HEURISTIC_LINE = re.compile(r"^-\s*(?P<phrases>.+?)\s*→\s*(?P<feature_id>F[1-8])\s*$")
_PHRASE = re.compile(r'"([^"]+)"')


class RoutingTableError(SentinelAgentError):
    """The prompt's ROUTING HEURISTICS section failed to parse."""


def parse_routing_heuristics(prompt_text: str) -> dict[FeatureID, list[str]]:
    try:
        section = prompt_text.split(_SECTION_HEADER, 1)[1].split(_NEXT_SECTION_HEADER, 1)[0]
    except IndexError as exc:
        raise RoutingTableError(
            f"prompt is missing a {_SECTION_HEADER!r}...{_NEXT_SECTION_HEADER!r} section"
        ) from exc

    heuristics: dict[FeatureID, list[str]] = {}
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _HEURISTIC_LINE.match(stripped)
        if match is None:
            raise RoutingTableError(f"unparseable routing heuristic line: {stripped!r}")
        feature_id: FeatureID = match["feature_id"]  # type: ignore[assignment]
        phrases = _PHRASE.findall(match["phrases"])
        if not phrases:
            raise RoutingTableError(f"routing heuristic line has no quoted phrases: {stripped!r}")
        heuristics.setdefault(feature_id, []).extend(phrases)
    return heuristics


def route(
    query_text: str, *, heuristics: dict[FeatureID, list[str]] | None = None
) -> list[FeatureID]:
    """Keyword-match approximation of Prime's routing, capped to
    `MAX_PARALLEL_COLLABORATORS`. Feature IDs are returned in descending
    order of how many of their phrases matched, ties broken by F1..F8
    order (deterministic, cheap to assert against in tests).
    """
    table = heuristics if heuristics is not None else parse_routing_heuristics(load_prime_prompt())
    lowered = query_text.lower()

    scored: list[tuple[int, FeatureID]] = []
    for feature_id, phrases in table.items():
        hits = sum(1 for phrase in phrases if phrase.lower() in lowered)
        if hits > 0:
            scored.append((hits, feature_id))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [feature_id for _, feature_id in scored[:MAX_PARALLEL_COLLABORATORS]]
