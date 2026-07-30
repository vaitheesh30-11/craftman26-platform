"""Every contract must reject unknown fields (extra='forbid')."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from iam_sentinel_agents.contracts import (
    AwsDocCitation,
    DecisionRecord,
    EvidenceRef,
    Finding,
    RemediationPlan,
    SentinelQuery,
    SpecialistTask,
    SpecialistVerdict,
    ToolInvocation,
    UntrustedContextBlock,
    ZelkovaCheck,
)

from tests.contract._factories import (
    make_citation,
    make_decision,
    make_evidence_ref,
    make_finding,
    make_query,
    make_remediation_dry,
    make_task,
    make_tool_invocation,
    make_verdict,
    make_zelkova_pass,
)

pytestmark = pytest.mark.contract

_CASES = [
    (AwsDocCitation, make_citation),
    (EvidenceRef, make_evidence_ref),
    (Finding, make_finding),
    (ZelkovaCheck, make_zelkova_pass),
    (RemediationPlan, make_remediation_dry),
    (ToolInvocation, make_tool_invocation),
    (SpecialistVerdict, make_verdict),
    (SentinelQuery, make_query),
    (SpecialistTask, make_task),
    (DecisionRecord, make_decision),
    (UntrustedContextBlock, lambda: UntrustedContextBlock(type="role_names", body="role/x")),
]


@pytest.mark.parametrize(("model_cls", "instance_factory"), _CASES)
def test_unknown_field_rejected(model_cls, instance_factory) -> None:
    payload = json.loads(instance_factory().model_dump_json(by_alias=True))
    payload["definitely_not_a_real_field"] = "surprise!"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model_cls.model_validate(payload)


@pytest.mark.parametrize(("model_cls", "instance_factory"), _CASES)
def test_models_are_frozen(model_cls, instance_factory) -> None:
    instance = instance_factory()
    with pytest.raises(ValidationError):
        setattr(instance, next(iter(model_cls.model_fields)), None)
