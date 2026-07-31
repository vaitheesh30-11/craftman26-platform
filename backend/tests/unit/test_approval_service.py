"""Unit tests for `services/approval_service.py` (backend phase-03 §6).

Per this repo's revised testing policy: focused unit tests over Step
Functions Local / property tests (deferred, see this phase's ADR). The
state machine itself does not exist yet, so `StepFunctionsClient` is a
`MagicMock` throughout -- these tests prove `ApprovalService`'s own
orchestration (idempotency, decision-status transitions, graceful
degrade), not the callee's actual behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.compute.step_functions_client import SyncExecutionResult

from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.approval_service import ApprovalService
from iam_sentinel_backend.settings import settings

_PRINCIPAL = Principal(arn="arn:aws:iam::111122223333:role/Alice", auth_kind="cognito")
_DECISION_ID = "01DECISIONID000000000000A"
_ARN = "arn:aws:states:us-east-1:111122223333:stateMachine:SentinelApprovalApply"


def _remediation(action: str = "attach_inline_policy") -> dict[str, object]:
    return {"action": action, "target_arn": "arn:aws:iam::111122223333:role/Bob", "dry_run": False}


def _decision(
    status: str = "ANSWERED", remediations: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "principal": _PRINCIPAL.arn,
        "correlation_id": "01CORRELATIONID00000000A",
        "decided_at": "2026-07-30T00:00:00+00:00",
        "decision_id": _DECISION_ID,
        "status": status,
        "remediations_proposed": remediations if remediations is not None else [_remediation()],
    }


def _service(
    *,
    decisions: MagicMock | None = None,
    sfn: MagicMock | None = None,
    ssm: MagicMock | None = None,
) -> tuple[ApprovalService, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    decisions = decisions or MagicMock()
    idempotency = MagicMock()
    idempotency.get_record.return_value = None
    idempotency.claim_for_result.return_value = True
    sfn = sfn or MagicMock()
    if ssm is None:
        ssm = MagicMock()
        ssm.get_parameter.return_value = _ARN
    evidence = MagicMock()
    service = ApprovalService(
        decisions,
        idempotency_client=idempotency,
        step_functions_client=sfn,
        ssm_client=ssm,
        evidence_client=evidence,
    )
    return service, decisions, idempotency, sfn, ssm, evidence


def test_approve_happy_path_succeeds_and_marks_auto_remediated() -> None:
    decisions = MagicMock()
    decisions.get_by_id.return_value = _decision()
    sfn = MagicMock()
    sfn.start_sync_execution.return_value = SyncExecutionResult(
        execution_arn="arn:aws:states:...:execution:x",
        output={"state": "SUCCEEDED", "remediation_applied": _remediation()},
    )
    service, _, idempotency, _, _, _ = _service(decisions=decisions, sfn=sfn)

    result = service.approve(
        principal=_PRINCIPAL,
        decision_id=_DECISION_ID,
        remediation_index=0,
        reason="ok",
        dry_run=False,
    )

    assert result.state == "SUCCEEDED"
    assert result.state_machine_execution_arn == "arn:aws:states:...:execution:x"
    decisions.put.assert_called_once()
    updated = decisions.put.call_args.args[0]
    assert updated["status"] == "AUTO_REMEDIATED"
    idempotency.store_result.assert_called_once()


def test_approve_zelkova_precheck_rejection_does_not_transition_decision() -> None:
    """The state machine's own `ZelkovaPreCheck` state (phase-03 §4, deferred
    with the rest of `SentinelApprovalApply`) reports a business-level
    `state=REJECTED` in its output -- a valid, non-error outcome the caller
    must surface as-is, not translate into an HTTP error.
    """
    decisions = MagicMock()
    decisions.get_by_id.return_value = _decision()
    sfn = MagicMock()
    sfn.start_sync_execution.return_value = SyncExecutionResult(
        execution_arn="arn:aws:states:...:execution:y",
        output={"state": "REJECTED", "witness": {"action": "s3:*"}},
    )
    service, _, _, _, _, _ = _service(decisions=decisions, sfn=sfn)

    result = service.approve(
        principal=_PRINCIPAL,
        decision_id=_DECISION_ID,
        remediation_index=0,
        reason="ok",
        dry_run=False,
    )

    assert result.state == "REJECTED"
    decisions.put.assert_not_called()


def test_approve_idempotent_replay_does_not_call_state_machine_twice() -> None:
    decisions = MagicMock()
    decisions.get_by_id.return_value = _decision()
    sfn = MagicMock()
    sfn.start_sync_execution.return_value = SyncExecutionResult(
        execution_arn="arn:aws:states:...:execution:z", output={"state": "SUCCEEDED"}
    )
    service, _, idempotency, _, _, _ = _service(decisions=decisions, sfn=sfn)

    first = service.approve(
        principal=_PRINCIPAL,
        decision_id=_DECISION_ID,
        remediation_index=0,
        reason="ok",
        dry_run=False,
    )

    stored_call = idempotency.store_result.call_args
    idempotency.get_record.return_value = {
        "input_hash": _input_hash_from_call(stored_call),
        "status": "COMPLETED",
        "result": first.model_dump(),
    }

    second = service.approve(
        principal=_PRINCIPAL,
        decision_id=_DECISION_ID,
        remediation_index=0,
        reason="ok",
        dry_run=False,
    )

    assert second == first
    sfn.start_sync_execution.assert_called_once()


def _input_hash_from_call(call: object) -> str:
    assert call is not None
    return str(call.kwargs["input_hash"])


def test_approve_returns_503_when_state_machine_not_configured() -> None:
    decisions = MagicMock()
    decisions.get_by_id.return_value = _decision()
    ssm = MagicMock()
    ssm.get_parameter.return_value = None
    service, _, idempotency, sfn, _, _ = _service(decisions=decisions, ssm=ssm)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.approve(
            principal=_PRINCIPAL,
            decision_id=_DECISION_ID,
            remediation_index=0,
            reason="",
            dry_run=False,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "APPROVAL_STATE_MACHINE_NOT_CONFIGURED"
    idempotency.claim_for_result.assert_not_called()
    sfn.start_sync_execution.assert_not_called()


def test_approve_404_when_remediation_index_out_of_range() -> None:
    decisions = MagicMock()
    decisions.get_by_id.return_value = _decision(remediations=[])
    service, _, _, _, _, _ = _service(decisions=decisions)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.approve(
            principal=_PRINCIPAL,
            decision_id=_DECISION_ID,
            remediation_index=0,
            reason="",
            dry_run=False,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "REMEDIATION_NOT_FOUND"


def test_approve_409_when_decision_already_resolved() -> None:
    decisions = MagicMock()
    decisions.get_by_id.return_value = _decision(status="REJECTED")
    service, _, _, _, _, _ = _service(decisions=decisions)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.approve(
            principal=_PRINCIPAL,
            decision_id=_DECISION_ID,
            remediation_index=0,
            reason="",
            dry_run=False,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "DECISION_NOT_TRANSITIONABLE"


def test_reject_records_rejection_and_emits_evidence_without_state_machine() -> None:
    decisions = MagicMock()
    decisions.get_by_id.return_value = _decision()
    service, _, _, sfn, _, evidence = _service(decisions=decisions)

    result = service.reject(
        principal=_PRINCIPAL,
        decision_id=_DECISION_ID,
        remediation_index=0,
        reason="prefer manual review",
    )

    assert result.state == "REJECTED"
    decisions.put.assert_called_once()
    updated = decisions.put.call_args.args[0]
    assert updated["status"] == "REJECTED"
    assert len(updated["remediations_rejected"]) == 1
    evidence.put_signed_evidence.assert_called_once()
    assert evidence.put_signed_evidence.call_args.kwargs["kind"] == "approval_decision"
    sfn.start_sync_execution.assert_not_called()


def test_approval_state_machine_ssm_param_is_stage_scoped() -> None:
    assert (
        settings.approval_state_machine_ssm_param
        == f"/sentinel/{settings.stage}/approval/state-machine-arn"
    )
