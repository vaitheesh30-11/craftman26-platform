"""Shared base classes and enums (mirrors `docs/DATA_CONTRACTS.md`'s
`Base`/`FeatureID`/`Severity`/`Verdict`, see `schemas/__init__.py`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FeatureID = Literal["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
DecisionStatus = Literal["ANSWERED", "ESCALATED", "AUTO_REMEDIATED", "REJECTED"]


class RequestBase(BaseModel):
    """Every inbound request body: unknown fields are a client bug, not
    silently dropped input, so `extra="forbid"`.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)


class ResponseBase(BaseModel):
    """Every outbound response body. `extra="ignore"` because these models
    parse DDB table-client dicts directly (`FindingsClient`/`DecisionsClient`
    return plain dicts that also carry the table's internal composite-key
    attributes, e.g. `account_id#feature_id` -- see `adapters/ddb/findings.
    py`'s module docstring) -- those are storage plumbing, not part of the
    public wire contract, and must not fail validation.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    correlation_id: str
