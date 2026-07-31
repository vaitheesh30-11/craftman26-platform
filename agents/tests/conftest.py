"""Shared pytest fixtures for the agents module."""

from __future__ import annotations

import hashlib
import unicodedata
from typing import TYPE_CHECKING

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.contracts.finding import set_quote_manifest_provider

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mypy_boto3_dynamodb.service_resource import Table

_REGION = "us-east-1"


class _InMemoryManifest:
    def __init__(self, quotes: list[str]) -> None:
        self._hashes = {self._hash(q) for q in quotes}

    @staticmethod
    def _hash(quote: str) -> str:
        normalized = unicodedata.normalize("NFKC", quote)
        collapsed = " ".join(normalized.split())
        return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()

    def contains(self, quote_sha256: str) -> bool:
        return quote_sha256 in self._hashes


CANONICAL_QUOTES: list[str] = [
    "PassRole is not an API call. No CloudTrail logs are generated for iam:PassRole. "
    "The iam:PassRole action is not tracked and is not included in IAM action last "
    "accessed information. It is not included in generated policies.",
    "Custom policy checks are environment-agnostic in their analysis. Their analysis "
    "only considers information contained within the input policies. For example, "
    "custom policy checks cannot check whether an account is a member of a specific "
    "AWS organization. Therefore, the custom policy checks cannot compare new access "
    "based on condition key values for the aws:PrincipalOrgId and aws:PrincipalAccount "
    "condition keys.",
    "Data events not available — IAM Access Analyzer does not identify action-level "
    "activity for data events, such as Amazon S3 data events, in generated policies.",
    "By default, CloudTrail does not log data events such as Amazon S3 object-level "
    "activity (GetObject, DeleteObject).",
    "Test SCPs by creating an organizational unit and moving accounts into it.",
    "Ending an active session for an IAM Identity Center user doesn't end any active "
    "IAM role sessions in the AWS Management Console or AWS CLI.",
    "SCPs have no effect on users or roles in the management account.",
    "SCPs don't apply to the management account — your production workloads have no "
    "SCP guardrails.",
]


@pytest.fixture(autouse=True)
def _install_fixture_manifest() -> Iterator[None]:
    manifest = _InMemoryManifest(CANONICAL_QUOTES)
    set_quote_manifest_provider(lambda: manifest)
    yield
    set_quote_manifest_provider(lambda: None)


@pytest.fixture
def known_quote() -> str:
    return CANONICAL_QUOTES[0]


@pytest.fixture
def unknown_quote() -> str:
    return "This quote is not in any AWS documentation and must be rejected."


# agents-phase-16 (cost guardrails, docs/decisions/0032): mirrors
# adapters/tests/conftest.py's `aws_credentials`/`moto_session`/
# `budget_table`/`breakers_table`/`ssm_client` fixtures. Duplicated rather
# than imported cross-package -- adapters/tests is not on this module's
# pytest path, and this repo already tolerates this kind of fixture
# duplication (e.g. `policies_table` is defined twice in adapters/tests/
# conftest.py itself).
@pytest.fixture
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _REGION)


@pytest.fixture
def moto_session(aws_credentials: None) -> Iterator[None]:
    with mock_aws():
        yield


@pytest.fixture
def budget_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelBudget-test",
        KeySchema=[
            {"AttributeName": "correlation_id", "KeyType": "HASH"},
            {"AttributeName": "sample_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "correlation_id", "AttributeType": "S"},
            {"AttributeName": "sample_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelBudget-test")


@pytest.fixture
def breakers_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelBreakers-test",
        KeySchema=[{"AttributeName": "breaker_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "breaker_name", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelBreakers-test")


@pytest.fixture
def ssm_client(moto_session: None) -> boto3.client:
    return boto3.client("ssm", region_name=_REGION)


@pytest.fixture
def reports_bucket(moto_session: None) -> str:
    bucket_name = "sentinel-reports-test"
    boto3.client("s3", region_name=_REGION).create_bucket(Bucket=bucket_name)
    return bucket_name
