"""`POST /decisions/{id}/approve|reject` (backend phase-03 §3-5).

Scoping note (see `docs/decisions/` for the numbered ADR): phase-03's own
§2 asks for a real Step Functions Standard state machine
(`SentinelApprovalApply`) that does pre-check -> apply -> wait -> post-check
-> success/rollback -- that is `aws-infra`'s deliverable per this repo's
module boundary (CDK lives in `aws-infra/`, `backend/` only calls AWS
through `adapters/`), and it has not been built yet. `approve()` below is
built against §3's documented `states:StartSyncExecution` contract (steps
1-3) and does not itself run Zelkova or mutate any policy -- the same
"build the caller against the documented contract, defer the callee"
precedent ADR 0017 and ADR 0018 decision 1 already set. The state
machine's ARN is resolved from SSM (`settings.approval_state_machine_ssm_
param`) rather than hardcoded, so it degrades to a clear error instead of
crashing when that parameter hasn't been published yet.

Reject (§5) has no callee to defer -- it is a pure DDB status transition
plus one evidence blob, fully implemented here.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

from fastapi import status
from iam_sentinel_adapters.compute.step_functions_client import StepFunctionsExecutionFailedError
from iam_sentinel_adapters.errors import SentinelAdapterError
from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.schemas.approvals import ApprovalResponse
from iam_sentinel_backend.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_adapters.compute.step_functions_client import StepFunctionsClient
    from iam_sentinel_adapters.ddb.decisions import DecisionsClient
    from iam_sentinel_adapters.ddb.idempotency import IdempotencyClient
    from iam_sentinel_adapters.evidence.client import EvidenceClient
    from iam_sentinel_adapters.ssm.params import SsmParameterClient

    from iam_sentinel_backend.auth.principal import Principal

_TRANSITIONABLE_STATUSES = {"ANSWERED", "ESCALATED"}
_APPROVABLE_ACTIONS = {
    "attach_inline_policy",
    "detach_inline_policy",
    "update_scp",
    "archive_finding",
    "enable_cloudtrail_data_events",
    "auto_generate_policy",
}
# state machine's own business outcome -> the decision's next status.
_OUTCOME_TO_DECISION_STATUS = {
    "SUCCEEDED": "AUTO_REMEDIATED",
    "ROLLED_BACK": "ESCALATED",  # rollback fired; needs a human look, phase-03 §4 Rollback state.
}


class ApprovalService:
    def __init__(
        self,
        decisions_client: DecisionsClient,
        *,
        idempotency_client: IdempotencyClient,
        step_functions_client: StepFunctionsClient,
        ssm_client: SsmParameterClient,
        evidence_client: EvidenceClient,
    ) -> None:
        self._decisions = decisions_client
        self._idempotency = idempotency_client
        self._step_functions = step_functions_client
        self._ssm = ssm_client
        self._evidence = evidence_client

    def approve(
        self,
        *,
        principal: Principal,
        decision_id: str,
        remediation_index: int,
        reason: str,
        dry_run: bool,
    ) -> ApprovalResponse:
        item, remediation = self._load_transitionable_remediation(
            principal=principal, decision_id=decision_id, remediation_index=remediation_index
        )

        key = _idempotency_key(decision_id, remediation_index, principal.arn)
        input_hash = _sha256_hex({"remediation": remediation, "dry_run": dry_run, "reason": reason})

        cached = self._idempotency.get_record(key)
        if cached is not None:
            return self._replay_or_conflict(cached, input_hash=input_hash)

        state_machine_arn = self._ssm.get_parameter(settings.approval_state_machine_ssm_param)
        if state_machine_arn is None:
            raise SentinelHTTPException(
                code="APPROVAL_STATE_MACHINE_NOT_CONFIGURED",
                message=(
                    f"no value at SSM parameter {settings.approval_state_machine_ssm_param!r} -- "
                    "SentinelApprovalApply has not been deployed yet"
                ),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not self._idempotency.claim_for_result(key, input_hash=input_hash):
            # Lost a race with a concurrent identical request between the
            # read above and this claim attempt -- re-read once rather than
            # double-invoking the state machine.
            raced = self._idempotency.get_record(key)
            if raced is not None:
                return self._replay_or_conflict(raced, input_hash=input_hash)

        try:
            execution = self._step_functions.start_sync_execution(
                state_machine_arn=state_machine_arn,
                input_payload={
                    "decision_id": decision_id,
                    "remediation": remediation,
                    "principal_arn": principal.arn,
                    "correlation_id": item.get("correlation_id", decision_id),
                    "dry_run": dry_run,
                },
                name=key[:80],
            )
        except (StepFunctionsExecutionFailedError, SentinelAdapterError) as exc:
            self._idempotency.store_result(
                key, input_hash=input_hash, status="FAILED", result={"error": str(exc)}
            )
            raise SentinelHTTPException(
                code="APPROVAL_EXECUTION_FAILED",
                message=str(exc),
                http_status=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        outcome_state = str(execution.output.get("state", "SUCCEEDED"))
        response = ApprovalResponse(
            decision_id=decision_id,
            remediation_applied=dict(execution.output.get("remediation_applied", remediation)),
            state_machine_execution_arn=execution.execution_arn,
            state=outcome_state,
        )
        self._idempotency.store_result(
            key, input_hash=input_hash, status="COMPLETED", result=response.model_dump()
        )

        new_status = _OUTCOME_TO_DECISION_STATUS.get(outcome_state)
        if new_status is not None:
            self._apply_decision_update(
                item,
                remediation_index=remediation_index,
                remediation_applied=response.remediation_applied,
                new_status=new_status,
                approval_actor=principal.arn,
                reason=reason,
            )
        return response

    def reject(
        self, *, principal: Principal, decision_id: str, remediation_index: int, reason: str
    ) -> ApprovalResponse:
        item, remediation = self._load_transitionable_remediation(
            principal=principal, decision_id=decision_id, remediation_index=remediation_index
        )

        decided_at = datetime.now(UTC).isoformat()
        rejected = {**remediation, "rejected_at": decided_at, "rejected_reason": reason}
        remediations_rejected = [*item.get("remediations_rejected", []), rejected]

        updated = {
            **item,
            "status": "REJECTED",
            "remediations_rejected": remediations_rejected,
            "approval_reason": reason,
            "approval_actor": principal.arn,
            "approval_decided_at": decided_at,
        }
        self._decisions.put(updated)

        self._evidence.put_signed_evidence(
            kind="approval_decision",
            correlation_id=item.get("correlation_id", decision_id),
            feature_id=_feature_id_for(item),
            body={
                "decision_id": decision_id,
                "remediation_index": remediation_index,
                "remediation": remediation,
                "outcome": "REJECTED",
                "reason": reason,
                "actor": principal.arn,
                "decided_at": decided_at,
            },
        )

        return ApprovalResponse(
            decision_id=decision_id, remediation_applied=remediation, state="REJECTED"
        )

    def _load_transitionable_remediation(
        self, *, principal: Principal, decision_id: str, remediation_index: int
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        item = self._decisions.get_by_id(decision_id, principal=principal.arn)
        if item is None:
            raise SentinelHTTPException(
                code="DECISION_NOT_FOUND",
                message=f"no decision {decision_id!r} for this principal",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        if item.get("status") not in _TRANSITIONABLE_STATUSES:
            raise SentinelHTTPException(
                code="DECISION_NOT_TRANSITIONABLE",
                message=f"decision {decision_id!r} is already {item.get('status')!r}",
                http_status=status.HTTP_409_CONFLICT,
            )

        # `remediations_proposed` is only present once the producer
        # (`agents/prime/post_turn.py`) writes it -- today it does not (see
        # this phase's ADR); this 404s cleanly rather than raising an
        # IndexError once that gap closes and a caller passes a real index.
        remediations = item.get("remediations_proposed") or []
        if not (0 <= remediation_index < len(remediations)):
            raise SentinelHTTPException(
                code="REMEDIATION_NOT_FOUND",
                message=(
                    f"decision {decision_id!r} has no remediations_proposed[{remediation_index}]"
                ),
                http_status=status.HTTP_404_NOT_FOUND,
            )
        remediation = dict(remediations[remediation_index])
        if remediation.get("action") not in _APPROVABLE_ACTIONS:
            raise SentinelHTTPException(
                code="INVALID_REMEDIATION_ACTION",
                message=f"{remediation.get('action')!r} is not an approvable remediation action",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return item, remediation

    def _replay_or_conflict(self, cached: dict[str, Any], *, input_hash: str) -> ApprovalResponse:
        if cached.get("input_hash") != input_hash:
            raise SentinelHTTPException(
                code="IDEMPOTENCY_KEY_CONFLICT",
                message="the same approval key was reused with a different request body",
                http_status=status.HTTP_409_CONFLICT,
            )
        if cached.get("status") == "RUNNING":
            raise SentinelHTTPException(
                code="APPROVAL_IN_PROGRESS",
                message="an identical approval request is already in flight",
                http_status=status.HTTP_409_CONFLICT,
            )
        if cached.get("status") == "FAILED":
            raise SentinelHTTPException(
                code="APPROVAL_EXECUTION_FAILED",
                message=str(cached.get("result", {}).get("error", "prior execution failed")),
                http_status=status.HTTP_502_BAD_GATEWAY,
            )
        return ApprovalResponse.model_validate(cached.get("result", {}))

    def _apply_decision_update(
        self,
        item: dict[str, Any],
        *,
        remediation_index: int,
        remediation_applied: dict[str, Any],
        new_status: str,
        approval_actor: str,
        reason: str,
    ) -> None:
        remaining = [
            remediation
            for index, remediation in enumerate(item.get("remediations_proposed") or [])
            if index != remediation_index
        ]
        applied = [*item.get("remediations_applied", []), remediation_applied]
        updated = {
            **item,
            "status": new_status,
            "remediations_proposed": remaining,
            "remediations_applied": applied,
            "approval_reason": reason,
            "approval_actor": approval_actor,
            "approval_decided_at": datetime.now(UTC).isoformat(),
        }
        self._decisions.put(updated)


def _idempotency_key(decision_id: str, remediation_index: int, principal_arn: str) -> str:
    raw = f"{decision_id}:{remediation_index}:{principal_arn}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sha256_hex(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_json(value).encode("utf-8")).hexdigest()


def _feature_id_for(item: dict[str, Any]) -> Any:
    """Evidence keys partition by a single `feature_id` (adapters/evidence/
    keys.py) -- a multi-specialist decision has no one "true" owner, so
    (mirroring `agents/prime/post_turn.py`'s own "no one true owner"
    rationale) this uses the first specialist verdict's `feature_id` when
    present, falling back to `F1` when it is not (see this phase's ADR: the
    persisted `DecisionRecord` does not carry `specialist_verdicts` today).
    """
    verdicts = item.get("specialist_verdicts") or []
    if verdicts and isinstance(verdicts[0], dict) and verdicts[0].get("feature_id"):
        return verdicts[0]["feature_id"]
    return "F1"
