"""Shadow-mode runner (agents phase-15 §3 "Shadow", §6 Step 3): fire the
fast and slow paths concurrently on the same input, respond with whichever
completes first, and persist a `DivergenceRecord` for the other.

Both paths are injected as plain async callables rather than hardwired to
`fast_path.py`/a live `bedrock-agent-runtime:InvokeAgent` call: this module
is exercised today with fakes (no deployed Bedrock Agent exists yet, same
gap this phase's ADR documents for `functions/router.py`'s escalation
path), and production wires the real fast-path dispatcher and a Bedrock
InvokeAgent coroutine in without this module changing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

from iam_sentinel_agents.contracts.routing import DivergenceKind, DivergenceRecord

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.divergence import DivergenceClient

    from iam_sentinel_agents.contracts.common import FeatureID

PathRunner = Callable[[], Awaitable[dict[str, Any]]]

# §6 Step 3.3: fields compared to decide `semantic_match` vs
# `material_disagreement`. `remediation` deliberately participates in the
# comparison too (the spec's own criterion is "different verdict OR
# different severity OR different remediation") even though it isn't named
# in the `verdict`/`severity`/`finding_ids` triple listed for `semantic_match`
# -- a `semantic_match` promise ("same verdict/severity/findings, narrative
# may differ") would otherwise silently paper over two paths proposing
# different fixes for the same finding.
_MATERIAL_FIELDS = ("verdict", "remediation")


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _finding_ids(output: dict[str, Any]) -> set[str]:
    findings = output.get("findings", [])
    if not isinstance(findings, list):
        return set()
    ids: set[str] = set()
    for finding in findings:
        if isinstance(finding, dict):
            ids.add(_canonical_hash(finding))
    return ids


def compute_divergence_kind(
    fast_output: dict[str, Any], slow_output: dict[str, Any]
) -> DivergenceKind:
    if _canonical_hash(fast_output) == _canonical_hash(slow_output):
        return "identical"
    if any(fast_output.get(field) != slow_output.get(field) for field in _MATERIAL_FIELDS):
        return "material_disagreement"
    if _finding_ids(fast_output) != _finding_ids(slow_output):
        return "material_disagreement"
    return "semantic_match"


def build_diff_summary(fast_output: dict[str, Any], slow_output: dict[str, Any]) -> str:
    differing = sorted(
        key
        for key in {*fast_output.keys(), *slow_output.keys()}
        if fast_output.get(key) != slow_output.get(key)
    )
    if not differing:
        return "no field-level differences"
    return f"differing fields: {', '.join(differing)}"


async def run_shadow(
    *,
    correlation_id: str,
    feature_id: FeatureID,
    input_payload: dict[str, Any],
    fast_runner: PathRunner,
    slow_runner: PathRunner,
    divergence_client: DivergenceClient | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], DivergenceRecord]:
    """§6 Step 3: run both paths concurrently, respond with whichever
    finishes first, persist the divergence between the two once both have
    completed. Returns `(response_body, divergence_record)` -- the caller
    (`functions/router.py`'s shadow branch, once wired) sends the first
    element back to the client immediately and the second to CloudWatch/DDB.
    """
    fast_task = asyncio.ensure_future(fast_runner())
    slow_task = asyncio.ensure_future(slow_runner())

    done, _pending = await asyncio.wait(
        {fast_task, slow_task}, return_when=asyncio.FIRST_COMPLETED
    )
    first_task = next(iter(done))
    response_body = first_task.result()

    fast_output = await fast_task
    slow_output = await slow_task

    divergence_kind = compute_divergence_kind(fast_output, slow_output)
    record = DivergenceRecord(
        correlation_id=correlation_id,
        feature_id=feature_id,
        input_hash=_canonical_hash(input_payload),
        fast_output=fast_output,
        slow_output=slow_output,
        divergence_kind=divergence_kind,
        diff_summary=build_diff_summary(fast_output, slow_output),
        reviewed=divergence_kind != "material_disagreement",
        detected_at=now or datetime.now(UTC),
    )
    if divergence_client is not None:
        divergence_client.put(record.model_dump(mode="json"))
    return response_body, record
