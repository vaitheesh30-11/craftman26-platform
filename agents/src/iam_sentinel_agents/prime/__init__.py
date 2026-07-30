"""Sentinel Prime — the supervisor agent (phase-01).

Bedrock's native multi-agent SUPERVISOR collaboration does the actual
specialist routing/fan-out server-side once Prime and its collaborators
are deployed (docs/decisions/0013). This package is everything on our
side of that boundary: the prompt's routing table parsed as data (for
drift-free testing, not duplicated logic), the RESULT-block parser, the
verdict-rollup + `DecisionRecord` composer, and the post-turn processor
that persists a turn's outcome.
"""

from __future__ import annotations
