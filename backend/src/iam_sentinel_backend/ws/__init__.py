"""WebSocket streaming surface (backend phase-02): `SentinelStream`'s
`$connect`/`$default`/`$disconnect` business logic, kept independent of the
Lambda event shape at the module boundary so it is unit-testable without a
live API Gateway WebSocket connection (`backend/docs/
phase-02-websocket-stream.txt`).

Per docs/decisions/0019, this package is real, tested code that is not yet
wired into `aws-infra`'s deployed `ws_connect`/`ws_default`/`ws_disconnect`
Lambdas -- that wiring is blocked by the pre-existing Lambda dependency-
bundling gap ADR 0011/0015/0017 already flagged (`iam_sentinel_backend`
still is not installed into any Lambda runtime).
"""

from __future__ import annotations
