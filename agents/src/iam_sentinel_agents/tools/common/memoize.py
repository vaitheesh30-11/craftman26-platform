"""`@memoize_procedural` (phase-14 §5 Step 5): wraps a deterministic tool
function so a repeat call with the same canonicalized input short-circuits
the compute via `SentinelMemoryProcedural` instead of re-running the LLM's
downstream engine.

Per phase-14 §9 risk mitigation ("procedural cache poisoning from a bad
prior computation ... `pattern_hash` includes the code version + engine
version, so a code change invalidates the cache"), the decorator's own
`version` argument is folded into the hash -- bump it whenever the wrapped
function's logic changes incompatibly with previously cached results.

Every function this decorator wraps returns `dict[str, Any]` (the same
JSON-dict convention every tool Lambda body follows, per
`tools/common/runtime.sentinel_handler`) -- `scp_engine.compute_effective_
policy`, `scp_engine.evaluate_action`, Athena result cursors, and Zelkova
checks all already return plain dicts, so no Pydantic round-trip is needed
here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any, ParamSpec, TYPE_CHECKING

from iam_sentinel_adapters.memory.client import MemoryClient

if TYPE_CHECKING:
    from collections.abc import Callable

_P = ParamSpec("_P")
JsonDict = dict[str, Any]


def _canonicalize(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    payload = {"args": args, "kwargs": kwargs}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_pattern_hash(*, version: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    canonical = f"{version}:{_canonicalize(args, kwargs)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def memoize_procedural(
    kind: str,
    ttl_seconds: int,
    *,
    version: str = "v1",
    memory: MemoryClient | None = None,
) -> Callable[[Callable[_P, JsonDict]], Callable[_P, JsonDict]]:
    """Decorator factory. `kind` is the DDB `pattern_kind` partition value
    (e.g. `scp_effective_policy`); `ttl_seconds` is the kind-specific TTL
    from phase-14 §3.4 (15 min for SCPs, 24 h for Athena results, 1 h for
    Zelkova checks).
    """

    def decorator(func: Callable[_P, JsonDict]) -> Callable[_P, JsonDict]:
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> JsonDict:
            client = memory or MemoryClient()
            pattern_hash = compute_pattern_hash(version=version, args=args, kwargs=kwargs)

            cached = client.procedural_get(kind, pattern_hash)
            if cached is not None and not _is_expired(cached):
                result = cached["result"]
                assert isinstance(result, dict)
                return result

            computed: JsonDict = func(*args, **kwargs)
            client.procedural_put(kind, pattern_hash, computed, ttl_seconds)
            return computed

        return wrapper

    return decorator


def _is_expired(cached: JsonDict) -> bool:
    """DDB TTL deletion is asynchronous (best-effort, up to 48h per AWS
    docs) -- a read can observe an item past its `expires_at` before the
    background sweep removes it. Treat that as a miss client-side so TTL
    expiry is exact from the caller's point of view.

    `expires_at` comes back from `boto3`'s DynamoDB *resource* API (not
    the low-level client), which decodes DynamoDB Number attributes as
    `decimal.Decimal`, not `int` -- `isinstance(..., int)` alone would
    silently treat every real cached item as non-expired.
    """
    expires_at = cached.get("expires_at")
    if not isinstance(expires_at, int | Decimal):
        return False
    return int(expires_at) <= int(datetime.now(UTC).timestamp())
