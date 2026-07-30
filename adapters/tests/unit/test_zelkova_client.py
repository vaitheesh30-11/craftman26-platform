from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_adapters.errors import ZelkovaError
from iam_sentinel_adapters.zelkova.client import ZelkovaClient


class _ThrottlingException(Exception):
    pass


def _make_client() -> tuple[ZelkovaClient, MagicMock, MagicMock, MagicMock, MagicMock]:
    access_analyzer = MagicMock()
    access_analyzer.exceptions.ThrottlingException = _ThrottlingException
    iam = MagicMock()
    cost_meter = MagicMock()
    cost_meter.projected.return_value = 0.0
    evidence = MagicMock()
    breaker = MagicMock()
    breaker.raise_if_open.return_value = None

    client = ZelkovaClient(
        access_analyzer_client=access_analyzer,
        iam_client=iam,
        cost_meter=cost_meter,
        evidence_client=evidence,
        breaker=breaker,
    )
    return client, access_analyzer, iam, cost_meter, evidence


def test_check_no_new_access_pass_emits_evidence_and_cost() -> None:
    client, access_analyzer, _, cost_meter, evidence = _make_client()
    access_analyzer.check_no_new_access.return_value = {"result": "PASS"}

    result = client.check_no_new_access(
        existing={"Version": "2012-10-17", "Statement": []},
        candidate={"Version": "2012-10-17", "Statement": []},
        correlation_id="corr-1",
        feature_id="F3",
    )

    assert result.pass_ is True
    assert result.result == "PASS"
    assert result.witness is None
    evidence.put_signed_evidence.assert_called_once()
    assert evidence.put_signed_evidence.call_args.kwargs["kind"] == "zelkova_invocation"
    cost_meter.record.assert_called_once()


def test_check_no_new_access_fail_returns_witness() -> None:
    client, access_analyzer, _, _, _ = _make_client()
    access_analyzer.check_no_new_access.return_value = {
        "result": "FAIL",
        "reasons": [{"description": "new statement grants s3:*", "statementIndex": 0}],
    }

    result = client.check_no_new_access(
        existing={"Statement": []},
        candidate={"Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]},
        correlation_id="corr-2",
        feature_id="F3",
    )

    assert result.pass_ is False
    assert result.result == "FAIL"
    assert result.witness is not None
    assert result.witness.context["reasons"][0]["description"] == "new statement grants s3:*"


def test_check_no_new_access_retries_then_passes_on_throttling() -> None:
    client, access_analyzer, _, _, _ = _make_client()
    access_analyzer.check_no_new_access.side_effect = [
        _ThrottlingException("slow down"),
        {"result": "PASS"},
    ]

    result = client.check_no_new_access(
        existing={}, candidate={}, correlation_id="corr-3", feature_id="F3"
    )

    assert result.pass_ is True
    assert access_analyzer.check_no_new_access.call_count == 2


def test_check_no_new_access_raises_zelkova_error_never_passes_on_exhausted_throttle() -> None:
    client, access_analyzer, _, _, evidence = _make_client()
    access_analyzer.check_no_new_access.side_effect = _ThrottlingException("still slow")

    with pytest.raises(ZelkovaError):
        client.check_no_new_access(existing={}, candidate={}, correlation_id="corr-4", feature_id="F3")

    evidence.put_signed_evidence.assert_not_called()


def test_check_no_new_access_raises_zelkova_error_on_non_throttling_failure() -> None:
    client, access_analyzer, _, _, _ = _make_client()
    access_analyzer.check_no_new_access.side_effect = RuntimeError("boom")

    with pytest.raises(ZelkovaError):
        client.check_no_new_access(existing={}, candidate={}, correlation_id="corr-5", feature_id="F3")


def test_start_policy_generation_caches_job_id_per_principal() -> None:
    client, access_analyzer, _, _, _ = _make_client()
    access_analyzer.start_policy_generation.return_value = {"jobId": "job-1"}

    first = client.start_policy_generation(
        principal_arn="arn:aws:iam::111111111111:role/r1",
        cloudtrail_details={"trails": []},
        correlation_id="corr-6",
        feature_id="F3",
    )
    second = client.start_policy_generation(
        principal_arn="arn:aws:iam::111111111111:role/r1",
        cloudtrail_details={"trails": []},
        correlation_id="corr-6",
        feature_id="F3",
    )

    assert first == second == "job-1"
    access_analyzer.start_policy_generation.assert_called_once()


def test_get_generated_policy_returns_none_while_in_progress() -> None:
    client, access_analyzer, _, _, _ = _make_client()
    access_analyzer.get_generated_policy.return_value = {"jobDetails": {"status": "IN_PROGRESS"}}

    policy = client.get_generated_policy(job_id="job-1", correlation_id="corr-7", feature_id="F3")

    assert policy is None


def test_get_generated_policy_raises_on_failed_job() -> None:
    client, access_analyzer, _, _, _ = _make_client()
    access_analyzer.get_generated_policy.return_value = {
        "jobDetails": {"status": "FAILED", "jobError": {"code": "SERVICE_ERROR", "message": "nope"}}
    }

    with pytest.raises(ZelkovaError):
        client.get_generated_policy(job_id="job-1", correlation_id="corr-8", feature_id="F3")


def test_get_generated_policy_returns_policy_on_success() -> None:
    client, access_analyzer, _, _, _ = _make_client()
    access_analyzer.get_generated_policy.return_value = {
        "jobDetails": {"status": "SUCCEEDED"},
        "generatedPolicyResult": {
            "generatedPolicies": [{"policy": '{"Version": "2012-10-17", "Statement": []}'}]
        },
    }

    policy = client.get_generated_policy(job_id="job-1", correlation_id="corr-9", feature_id="F3")

    assert policy == {"Version": "2012-10-17", "Statement": []}


def test_check_access_not_granted_pass() -> None:
    client, access_analyzer, _, cost_meter, _ = _make_client()
    access_analyzer.check_access_not_granted.return_value = {"result": "PASS"}

    result = client.check_access_not_granted(
        policy={"Statement": []},
        access=[{"actions": ["s3:GetObject"]}],
        policy_type="IDENTITY_POLICY",
        correlation_id="corr-10",
        feature_id="F3",
    )

    assert result.pass_ is True
    cost_meter.record.assert_called_once()


def test_start_policy_generation_raises_zelkova_error_on_non_throttling_failure() -> None:
    client, access_analyzer, _, _, _ = _make_client()
    access_analyzer.start_policy_generation.side_effect = RuntimeError("service down")

    with pytest.raises(ZelkovaError):
        client.start_policy_generation(
            principal_arn="arn:aws:iam::111111111111:role/r1",
            cloudtrail_details={},
            correlation_id="corr-11",
            feature_id="F3",
        )


def test_client_post_check_delegates_to_run_post_check() -> None:
    client, access_analyzer, iam, _, _ = _make_client()
    expected = {"Version": "2012-10-17", "Statement": []}
    iam.get_role_policy.return_value = {"PolicyDocument": expected}
    access_analyzer.check_no_new_access.return_value = {"result": "PASS"}

    result = client.post_check(
        role_arn="arn:aws:iam::111111111111:role/r1",
        policy_name="inline",
        expected_policy=expected,
        wait_seconds=0,
        max_polls=1,
        correlation_id="corr-12",
        feature_id="F3",
    )

    assert result.pass_ is True
    access_analyzer.check_no_new_access.assert_called_once()
