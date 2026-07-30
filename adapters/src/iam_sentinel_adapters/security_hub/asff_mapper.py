"""Deterministic `Finding` -> AWS Security Hub ASFF mapping (phase-04 §9).

Adapters never imports agents' pydantic `Finding` model (module boundary,
adapters/README.md §1: "Never imports from agents/"); callers construct an
`AsffFindingInput` from their own `Finding` instance's fields instead. The
field names mirror `docs/DATA_CONTRACTS.md`'s `Finding` schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from iam_sentinel_adapters.evidence.keys import FeatureID

Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

_SCHEMA_VERSION = "2018-10-08"

_ASFF_TYPES: dict[FeatureID, list[str]] = {
    "F1": ["Software and Configuration Checks/Governance/PolicyDrift"],
    "F2": ["Effects/Data Exposure"],
    "F3": ["Software and Configuration Checks/Governance/PolicyDrift"],
    "F4": ["Software and Configuration Checks/Governance/PolicyDrift"],
    "F5": ["TTPs/Credential Access"],
    "F6": ["Software and Configuration Checks/Governance/PolicyDrift"],
    "F7": ["Software and Configuration Checks/Governance/PolicyDrift"],
    "F8": ["Software and Configuration Checks/Governance/PolicyDrift"],
}

_ASFF_SEVERITY_LABEL: dict[Severity, str] = {
    "INFO": "INFORMATIONAL",
    "LOW": "LOW",
    "MEDIUM": "MEDIUM",
    "HIGH": "HIGH",
    "CRITICAL": "CRITICAL",
}
_ASFF_SEVERITY_NORMALIZED: dict[Severity, int] = {
    "INFO": 0,
    "LOW": 30,
    "MEDIUM": 50,
    "HIGH": 70,
    "CRITICAL": 90,
}


@dataclass(frozen=True)
class AsffFindingInput:
    finding_id: str
    feature_id: FeatureID
    account_id: str
    severity: Severity
    title: str
    detail: str
    aws_doc_citation_quote: str
    principal_arn: str | None = None
    resource_arn: str | None = None


def finding_to_asff(
    finding: AsffFindingInput,
    *,
    region: str,
    security_hub_account_id: str,
    updated_at: str,
) -> dict[str, object]:
    resource_id = finding.principal_arn or finding.resource_arn or finding.account_id
    resource_type = "AwsIamRole" if finding.principal_arn else "AwsAccount"

    return {
        "SchemaVersion": _SCHEMA_VERSION,
        "Id": finding.finding_id,
        "ProductArn": (
            f"arn:aws:securityhub:{region}:{security_hub_account_id}:"
            f"product/{security_hub_account_id}/iam-sentinel"
        ),
        "GeneratorId": f"iam-sentinel/{finding.feature_id}",
        "AwsAccountId": finding.account_id,
        "Types": _ASFF_TYPES[finding.feature_id],
        "Severity": {
            "Label": _ASFF_SEVERITY_LABEL[finding.severity],
            "Normalized": _ASFF_SEVERITY_NORMALIZED[finding.severity],
        },
        "Title": finding.title,
        "Description": finding.detail,
        "Resources": [{"Type": resource_type, "Id": resource_id}],
        "Note": {
            "Text": f"AWS documentation confirms this gap: {finding.aws_doc_citation_quote}",
            "UpdatedBy": "iam-sentinel",
            "UpdatedAt": updated_at,
        },
    }
