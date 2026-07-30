"""`POST /agent/chat` request (mirrors `docs/DATA_CONTRACTS.md §1`
`SentinelQuery`, minus `principal`/`submitted_at` -- those come from the
authenticated `Principal` and the request clock, never from client input).
"""

from __future__ import annotations

from pydantic import Field

from iam_sentinel_backend.schemas.common import RequestBase


class ChatRequest(RequestBase):
    query_text: str = Field(min_length=1, max_length=4096)
    hints: dict[str, str] = Field(default_factory=dict)
    include_arns_in_output: bool = False
    # Per backend phase-01 §4 step 2: `include_streaming=true` belongs on
    # the WebSocket path (phase-02); this REST endpoint always runs the
    # non-streaming, up-to-25s-budget flow and rejects the flag outright
    # rather than silently ignoring a caller's explicit request for
    # streaming.
    include_streaming: bool = False
