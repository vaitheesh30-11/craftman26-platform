"""`Finding` read model (mirrors `docs/DATA_CONTRACTS.md §4`)."""

from __future__ import annotations

from pydantic import Field

from iam_sentinel_backend.schemas.common import FeatureID, ResponseBase, Severity


class AwsDocCitationOut(ResponseBase):
    gap_id: FeatureID
    quote: str
    source: str
    url: str
    retrieved_on: str


class FindingOut(ResponseBase):
    finding_id: str
    feature_id: FeatureID
    account_id: str
    principal_arn: str | None = None
    resource_arn: str | None = None
    severity: Severity
    title: str
    detail: str
    aws_doc_citation: AwsDocCitationOut
    payload: dict[str, object] = Field(default_factory=dict)
    detected_at: str
    expires_at: str | None = None
    evidence_ref: dict[str, object] | None = None
    status: str = "OPEN"


class FindingsPage(ResponseBase):
    items: list[FindingOut]
    next_token: str | None = None
