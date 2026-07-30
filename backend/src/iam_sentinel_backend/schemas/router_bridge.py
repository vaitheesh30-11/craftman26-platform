"""Fast-path request/response shapes (backend phase-01 §5 Router Bridge
Contract). Each F1-F8 fast-path route's `trusted_input` shape is that
feature's own phase doc contract (`docs/DATA_CONTRACTS.md §8`'s index) --
none of those specialist Lambdas exist yet to validate a stricter schema
against (F1 is the only one built so far, agents phase-02), so the request
body is a validated-but-open `dict[str, object]` passthrough: backend's job
here is routing and auth, not re-deriving each specialist's own input
contract ahead of that specialist landing. `router.execute`'s own contract
(agents phase-15, not yet built) is what ultimately validates `trusted_input`
against each `Fx`'s real schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from iam_sentinel_backend.schemas.common import FeatureID, RequestBase, ResponseBase

FastPathTarget = Literal["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]


class FastPathRequest(RequestBase):
    payload: dict[str, object] = Field(default_factory=dict)


class FastPathResponse(ResponseBase):
    target: FastPathTarget
    verdict: str
    reason: str
    findings: list[dict[str, object]] = Field(default_factory=list)
    remediation: dict[str, object] | None = None


class ShadowViolationsPage(ResponseBase):
    items: list[dict[str, object]]
    next_token: str | None = None


__all__ = ["FastPathRequest", "FastPathResponse", "FeatureID", "ShadowViolationsPage"]
