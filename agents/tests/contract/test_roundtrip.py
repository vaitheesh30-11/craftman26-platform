"""Round-trip every contract via model_dump_json → model_validate_json."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from iam_sentinel_agents.contracts import (
    AwsDocCitation,
    BlastPath,
    DecisionRecord,
    EvidenceRef,
    Finding,
    PassRoleBlastPayload,
    PassRoleEdge,
    RemediationPlan,
    SentinelQuery,
    SpecialistTask,
    SpecialistVerdict,
    ToolInvocation,
    UntrustedContextBlock,
    ZelkovaCheck,
)
from tests.contract._factories import (
    make_blast_path,
    make_citation,
    make_decision,
    make_evidence_ref,
    make_finding,
    make_passrole_blast_payload,
    make_passrole_edge,
    make_query,
    make_remediation_dry,
    make_task,
    make_tool_invocation,
    make_verdict,
    make_zelkova_pass,
)

pytestmark = pytest.mark.contract

if TYPE_CHECKING:
    from pydantic import BaseModel


@pytest.mark.parametrize(
    ("model_cls", "instance_factory"),
    [
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
        (PassRoleEdge, make_passrole_edge),
        (BlastPath, make_blast_path),
        (PassRoleBlastPayload, make_passrole_blast_payload),
    ],
)
def test_roundtrip_is_lossless(model_cls: type[BaseModel], instance_factory: object) -> None:
    original = instance_factory()  # type: ignore[operator]
    payload = original.model_dump_json(by_alias=True)
    restored = model_cls.model_validate_json(payload)
    assert restored == original
