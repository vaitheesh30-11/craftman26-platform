"""Typed wrappers over Access Analyzer's Zelkova-backed APIs (phase-02
§3-5): `CheckNoNewAccess`, `CheckAccessNotGranted`, `StartPolicyGeneration`,
`GetGeneratedPolicy`, plus the post-write consistency check.

Never fails open (phase-02 §1, §4): every code path either returns a
`ZelkovaResult` computed from a real Access Analyzer response, or raises
`ZelkovaError` -- there is no path that returns `pass_=True` from a caught
exception. `Policy.CAUTIOUS` retries throttling only; every other error
(including retry exhaustion) raises.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import boto3
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit

from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
from iam_sentinel_adapters.cost_meter import CostMeter, SpendKind
from iam_sentinel_adapters.errors import ThrottlingError, ZelkovaError
from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json
from iam_sentinel_adapters.evidence.client import EvidenceClient
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings
from iam_sentinel_adapters.zelkova.models import PolicyPair, Witness, ZelkovaResult
from iam_sentinel_adapters.zelkova.post_check import run_post_check

if TYPE_CHECKING:
    from collections.abc import Callable

    from iam_sentinel_adapters.evidence.keys import FeatureID

_ZELKOVA_COST_USD = 0.0005
_GENERATION_CACHE_TTL_SECONDS = 900.0  # 15 minutes, phase-02 §9 risk mitigation


class ZelkovaClient:
    def __init__(
        self,
        *,
        access_analyzer_client: Any = None,
        iam_client: Any = None,
        cost_meter: CostMeter | None = None,
        evidence_client: EvidenceClient | None = None,
        breaker: BreakerAccessor | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._client = access_analyzer_client or boto3.client(
            "accessanalyzer", region_name=settings.region
        )
        self._iam = iam_client or boto3.client("iam", region_name=settings.region)
        self._cost_meter = cost_meter or CostMeter()
        self._evidence = evidence_client or EvidenceClient()
        self._breaker = breaker or BreakerAccessor()
        self._metrics = metrics or Metrics(namespace=settings.metric_namespace)
        self._breaker_name = f"zelkova:{settings.region}"
        self._generation_cache: dict[str, tuple[str, float]] = {}

    def check_no_new_access(
        self,
        *,
        existing: dict[str, Any],
        candidate: dict[str, Any],
        policy_type: str = "IDENTITY_POLICY",
        correlation_id: str,
        feature_id: FeatureID,
    ) -> ZelkovaResult:
        return self._run_check(
            operation="check_no_new_access",
            call=lambda: self._check_no_new_access(
                existingPolicyDocument=canonicalize_json(existing),
                newPolicyDocument=canonicalize_json(candidate),
                policyType=policy_type,
            ),
            existing=existing,
            candidate=candidate,
            correlation_id=correlation_id,
            feature_id=feature_id,
        )

    def check_access_not_granted(
        self,
        *,
        policy: dict[str, Any],
        access: list[dict[str, Any]],
        policy_type: str,
        correlation_id: str,
        feature_id: FeatureID,
    ) -> ZelkovaResult:
        return self._run_check(
            operation="check_access_not_granted",
            call=lambda: self._check_access_not_granted(
                policyDocument=canonicalize_json(policy),
                access=access,
                policyType=policy_type,
            ),
            existing=policy,
            candidate={"access": access},
            correlation_id=correlation_id,
            feature_id=feature_id,
        )

    def start_policy_generation(
        self,
        *,
        principal_arn: str,
        cloudtrail_details: dict[str, Any],
        correlation_id: str,
        feature_id: FeatureID,
    ) -> str:
        cached = self._generation_cache.get(principal_arn)
        if cached is not None and time.monotonic() - cached[1] < _GENERATION_CACHE_TTL_SECONDS:
            return cached[0]

        self._breaker.raise_if_open(self._breaker_name)
        try:
            response = self._start_policy_generation(
                policyGenerationDetails={"principalArn": principal_arn},
                cloudTrailDetails=cloudtrail_details,
            )
        except ThrottlingError as exc:
            self._breaker.record_failure(self._breaker_name)
            raise ZelkovaError(
                f"StartPolicyGeneration throttling exhausted for {correlation_id!r}"
            ) from exc
        except Exception as exc:
            self._breaker.record_failure(self._breaker_name)
            raise ZelkovaError(
                f"StartPolicyGeneration failed for {correlation_id!r}: {exc}"
            ) from exc
        self._breaker.record_success(self._breaker_name)

        job_id: str = response["jobId"]
        self._generation_cache[principal_arn] = (job_id, time.monotonic())
        self._meter(correlation_id=correlation_id, feature_id=feature_id, operation="start_policy_generation")
        return job_id

    def get_generated_policy(
        self, *, job_id: str, correlation_id: str, feature_id: FeatureID
    ) -> dict[str, Any] | None:
        self._breaker.raise_if_open(self._breaker_name)
        try:
            response = self._get_generated_policy(jobId=job_id)
        except ThrottlingError as exc:
            self._breaker.record_failure(self._breaker_name)
            raise ZelkovaError(f"GetGeneratedPolicy throttling exhausted for {job_id!r}") from exc
        except Exception as exc:
            self._breaker.record_failure(self._breaker_name)
            raise ZelkovaError(f"GetGeneratedPolicy failed for {job_id!r}: {exc}") from exc
        self._breaker.record_success(self._breaker_name)

        status = response["jobDetails"]["status"]
        if status == "IN_PROGRESS":
            return None
        if status == "FAILED":
            job_error = response["jobDetails"].get("jobError", {})
            raise ZelkovaError(f"policy generation job {job_id!r} failed: {job_error}")

        self._meter(correlation_id=correlation_id, feature_id=feature_id, operation="get_generated_policy")
        generated = response["generatedPolicyResult"]["generatedPolicies"][0]["policy"]
        policy: dict[str, Any] = generated if isinstance(generated, dict) else _load_json(generated)
        return policy

    def post_check(
        self,
        *,
        role_arn: str,
        policy_name: str,
        expected_policy: dict[str, Any],
        wait_seconds: int = 15,
        max_polls: int = 3,
        correlation_id: str,
        feature_id: FeatureID,
    ) -> ZelkovaResult:
        return run_post_check(
            role_arn=role_arn,
            policy_name=policy_name,
            expected_policy=expected_policy,
            wait_seconds=wait_seconds,
            max_polls=max_polls,
            correlation_id=correlation_id,
            feature_id=feature_id,
            iam_client=self._iam,
            check_no_new_access=self.check_no_new_access,
        )

    def _run_check(
        self,
        *,
        operation: str,
        call: Callable[[], dict[str, Any]],
        existing: dict[str, Any],
        candidate: dict[str, Any],
        correlation_id: str,
        feature_id: FeatureID,
    ) -> ZelkovaResult:
        self._breaker.raise_if_open(self._breaker_name)
        start = time.monotonic()
        try:
            response = call()
        except ThrottlingError as exc:
            self._breaker.record_failure(self._breaker_name)
            raise ZelkovaError(f"{operation} throttling exhausted for {correlation_id!r}") from exc
        except Exception as exc:
            self._breaker.record_failure(self._breaker_name)
            raise ZelkovaError(f"{operation} failed for {correlation_id!r}: {exc}") from exc
        self._breaker.record_success(self._breaker_name)
        latency_ms = int((time.monotonic() - start) * 1000)

        outcome = response.get("result", "FAIL")
        passed = outcome == "PASS"
        witness = None if passed else _witness_from_reasons(response.get("reasons", []))
        pair = PolicyPair(
            existing=existing,
            candidate=candidate,
            existing_sha256=_sha256_hex(existing),
            candidate_sha256=_sha256_hex(candidate),
        )
        result = ZelkovaResult(
            pass_=passed,
            result=outcome,
            witness=witness,
            latency_ms=latency_ms,
            invoked_at=datetime.now(UTC),
            policy_pair=pair,
        )
        self._emit_evidence(result, correlation_id=correlation_id, feature_id=feature_id, operation=operation)
        self._meter(correlation_id=correlation_id, feature_id=feature_id, operation=operation)
        if not passed:
            self._metrics.add_metric(name="SentinelZelkovaViolations", unit=MetricUnit.Count, value=1)
        return result

    def _emit_evidence(
        self, result: ZelkovaResult, *, correlation_id: str, feature_id: FeatureID, operation: str
    ) -> None:
        pair = result.policy_pair
        self._evidence.put_signed_evidence(
            kind="zelkova_invocation",
            correlation_id=correlation_id,
            feature_id=feature_id,
            body={
                "operation": operation,
                "correlation_id": correlation_id,
                "existing_policy_sha256": pair.existing_sha256 if pair else "",
                "candidate_policy_sha256": pair.candidate_sha256 if pair else "",
                "result": result.result,
                "witness": _witness_to_dict(result.witness),
                "latency_ms": result.latency_ms,
                "invoked_at": result.invoked_at.isoformat(),
            },
        )

    def _meter(self, *, correlation_id: str, feature_id: FeatureID, operation: str) -> None:
        self._metrics.add_dimension(name="feature_id", value=feature_id)
        self._metrics.add_dimension(name="zelkova_operation", value=operation)
        self._metrics.add_metric(name="SentinelZelkovaInvocations", unit=MetricUnit.Count, value=1)
        self._cost_meter.record(
            correlation_id, SpendKind.ZELKOVA_INVOCATION, _ZELKOVA_COST_USD, feature_id=feature_id
        )

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _check_no_new_access(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._client.check_no_new_access(**kwargs))
        except self._client.exceptions.ThrottlingException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _check_access_not_granted(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._client.check_access_not_granted(**kwargs))
        except self._client.exceptions.ThrottlingException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _start_policy_generation(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._client.start_policy_generation(**kwargs))
        except self._client.exceptions.ThrottlingException as exc:
            raise ThrottlingError(str(exc)) from exc

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _get_generated_policy(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return dict(self._client.get_generated_policy(**kwargs))
        except self._client.exceptions.ThrottlingException as exc:
            raise ThrottlingError(str(exc)) from exc


def _witness_from_reasons(reasons: list[dict[str, Any]]) -> Witness:
    if not reasons:
        return Witness()
    first = reasons[0]
    return Witness(
        principal=str(first.get("principal", "")),
        action=str(first.get("action", "")),
        resource=str(first.get("resource", "")),
        context={"reasons": reasons},
    )


def _witness_to_dict(witness: Witness | None) -> dict[str, Any] | None:
    if witness is None:
        return None
    return {
        "principal": witness.principal,
        "action": witness.action,
        "resource": witness.resource,
        "context": witness.context,
    }


def _sha256_hex(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_json(value).encode("utf-8")).hexdigest()


def _load_json(value: str) -> dict[str, Any]:
    return dict(json.loads(value))
