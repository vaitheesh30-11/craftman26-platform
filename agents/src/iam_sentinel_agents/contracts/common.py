"""Shared primitives: Base model, enums, regex constants."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FeatureID = Literal["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
Verdict = Literal["CONFIRM", "REJECT", "ESCALATE", "INCONCLUSIVE", "REMEDIATED"]

ULID_PATTERN = r"^01[0-9A-HJKMNP-TV-Z]{24}$"
ACCOUNT_ID_PATTERN = r"^[0-9]{12}$"
ARN_PATTERN = r"^arn:aws:[a-z0-9-]+:[a-z0-9-]*:[0-9]*:.+$"
ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
SHA256_PATTERN = r"^[a-f0-9]{64}$"

SEVERITY_ORDER: dict[Severity, int] = {
    "INFO": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


class Base(BaseModel):
    """Base model for every IAM Sentinel contract.

    Frozen, extra-forbidden, whitespace-stripped, validate-on-assign.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
    )


def severity_max(a: Severity, b: Severity) -> Severity:
    return a if SEVERITY_ORDER[a] >= SEVERITY_ORDER[b] else b
