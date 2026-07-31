"""Prefix consolidation — phase-04 §4 Step 4.

`S3DataEventUsage.consolidated_prefix` (contracts/data_event.py) is a single
string per (action, bucket) usage group, while the underlying CloudTrail
data for that group is a flat list of concrete object keys. The phase doc's
two explicit thresholds ("> 5 distinct child paths under a prefix" and
"> 20 distinct root-level paths") describe *when* to widen scope, not how
to represent several disjoint scopes in one field — the contract only
carries one string. This implementation always resolves to the single most
specific common-prefix wildcard that keeps every observed key inside its
scope: it walks directory segments to find the longest shared prefix, then
collapses everything past that point into one `prefix/*`. Root-level fanout
over `_ROOT_FANOUT_LIMIT` is reported back to the caller as a warning flag
(the phase doc's own "per-Finding warning" for bucket-wide access) rather
than raising — a data-quality/coverage signal, not a fatal error, matching
this repo's existing precedent for degraded-but-valid results (see
`tools/f1/graph.py`'s `classify_reachable_roles` docstring).
"""

from __future__ import annotations

_ROOT_FANOUT_LIMIT = 20


def consolidate_prefix(object_keys: list[str]) -> tuple[str | None, bool]:
    """Return `(consolidated_prefix, bucket_wide_warning)` for one
    (action, bucket) usage group's concrete object keys.

    `None` is returned only when `object_keys` carries no non-empty key at
    all (e.g. an S3 event whose `requestParameters.key` was absent).
    `bucket_wide_warning=True` means root-level fanout exceeded
    `_ROOT_FANOUT_LIMIT` (§4 rule 4) and the caller must surface it rather
    than silently emit a bucket-wide `*` scope.
    """
    keys = sorted({key for key in object_keys if key})
    if not keys:
        return None, False
    if len(keys) == 1:
        return keys[0], False

    segments = [key.split("/") for key in keys]
    roots = {segment[0] for segment in segments}
    if len(roots) > _ROOT_FANOUT_LIMIT:
        return "*", True
    if len(roots) > 1:
        # No shared root at all -- the widest common scope is the bucket
        # itself, but fanout stayed within the explicit "bucket-wide" limit.
        return "*", False

    common_len = _longest_common_segment_prefix(segments)
    common_prefix = "/".join(segments[0][:common_len])

    if all(len(segment) == common_len for segment in segments):
        # Every key is exactly the common prefix -- no wildcard needed.
        return common_prefix, False

    return f"{common_prefix}/*", False


def _longest_common_segment_prefix(segments: list[list[str]]) -> int:
    shortest = min(len(segment) for segment in segments)
    common_len = 0
    for depth in range(shortest):
        values_at_depth = {segment[depth] for segment in segments}
        if len(values_at_depth) != 1:
            break
        common_len = depth + 1
    return common_len
