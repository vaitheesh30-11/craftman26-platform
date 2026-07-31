"""Moto-backed integration fixtures for phase-13 (agents/docs/phase-13-
integration-tests.txt Step 1). Every scenario in this package exercises
*real* production code -- `PrimePostTurnProcessor`, the DDB table clients,
`EvidenceClient`, `SnsClient`, real specialist tool functions -- against a
real (moto-mocked) AWS surface, never a hand-rolled fake standing in for
DynamoDB/S3/SNS/Organizations/SSO.

Two exceptions, both already established precedent elsewhere in this
codebase (not new deferrals invented for this phase):

- KMS signing uses the same hand-written `_FakeKms` moto's own docs warn
  about (`adapters/tests/unit/test_evidence_client.py` module docstring:
  "moto's mocked KMS does not implement real RSASSA-PSS cryptography").
  Real crypto is AWS's to verify, not this suite's.
- `SecurityHubClient` is a `MagicMock` here: ASFF import is not what these
  scenarios are proving (SNS + DDB + S3 + Organizations/SSO fan-out is),
  and moto's `batch_import_findings` coverage is not exercised elsewhere
  in this repo either -- adding it here would be new, unverified surface
  for a phase whose job is to integrate what already exists.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from unittest.mock import MagicMock

import boto3
import pytest
from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
from iam_sentinel_adapters.ddb.decisions import DecisionsClient
from iam_sentinel_adapters.ddb.idempotency import IdempotencyClient
from iam_sentinel_adapters.ddb.revocations import RevocationsClient
from iam_sentinel_adapters.evidence.client import EvidenceClient
from iam_sentinel_adapters.evidence.kms_signer import KmsSigner
from iam_sentinel_adapters.evidence.kms_verifier import KmsVerifier
from iam_sentinel_adapters.sns.client import SnsClient
from moto import mock_aws

from iam_sentinel_agents.prime.post_turn import PrimePostTurnProcessor

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mypy_boto3_dynamodb.service_resource import Table

# F1's fixtures attach real AWS managed policies (`AdministratorAccess`) --
# moto only loads its bundled copies of those policies when this env var is
# set (moto/settings.py: `load_iam_aws_managed_policies`; same precedent as
# `tests/unit/f1/conftest.py`). Set at collection time, before any
# `@mock_aws`/`mock_aws()` call creates an IAM backend.
os.environ.setdefault("MOTO_IAM_LOAD_MANAGED_POLICIES", "true")

_REGION = "us-east-1"
_EVIDENCE_BUCKET = "sentinel-evidence-e2e"
_KMS_KEY_ARN = "arn:aws:kms:us-east-1:111122223333:key/e2e-fake-key"


class _FakeKms:
    """Same digest-as-signature stand-in as
    `adapters/tests/unit/test_evidence_client.py` -- real enough to prove
    canonicalize -> hash -> sign -> store -> re-hash -> verify is wired
    correctly end to end; not a claim about AWS KMS's own cryptography.
    """

    def sign(
        self, *, KeyId: str, Message: bytes, MessageType: str, SigningAlgorithm: str
    ) -> dict[str, Any]:
        return {"Signature": Message}

    def verify(
        self,
        *,
        KeyId: str,
        Message: bytes,
        MessageType: str,
        Signature: bytes,
        SigningAlgorithm: str,
    ) -> dict[str, Any]:
        return {"SignatureValid": Signature == Message}


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
def breakers_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelBreakers-e2e",
        KeySchema=[{"AttributeName": "breaker_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "breaker_name", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelBreakers-e2e")


@pytest.fixture
def moto_breaker(breakers_table: Table) -> BreakerAccessor:
    return BreakerAccessor(table=breakers_table)


@pytest.fixture
def decisions_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelDecisions-e2e",
        KeySchema=[
            {"AttributeName": "principal", "KeyType": "HASH"},
            {"AttributeName": "decided_at", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "principal", "AttributeType": "S"},
            {"AttributeName": "decided_at", "AttributeType": "S"},
            {"AttributeName": "correlation_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "correlation-index",
                "KeySchema": [
                    {"AttributeName": "correlation_id", "KeyType": "HASH"},
                    {"AttributeName": "decided_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelDecisions-e2e")


@pytest.fixture
def idempotency_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelIdempotency-e2e",
        KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "correlation_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelIdempotency-e2e")


@pytest.fixture
def revocations_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelRevocations-e2e",
        KeySchema=[
            {"AttributeName": "account_id", "KeyType": "HASH"},
            {"AttributeName": "role_arn", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "account_id", "AttributeType": "S"},
            {"AttributeName": "role_arn", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelRevocations-e2e")


@pytest.fixture
def evidence_bucket(moto_session: None) -> str:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_EVIDENCE_BUCKET)
    # Real evidence buckets are versioned (production: `EvidenceRef.version_id`
    # is always a real S3 version id, never the `"unversioned"` fallback
    # `post_turn._to_agents_evidence_ref` uses only when a caller's bucket
    # genuinely isn't versioned) -- matching that here is what makes
    # `EvidenceClient.verify(...)` on a re-fetched ref work for real.
    s3.put_bucket_versioning(Bucket=_EVIDENCE_BUCKET, VersioningConfiguration={"Status": "Enabled"})
    return _EVIDENCE_BUCKET


@pytest.fixture
def critical_findings_topic_arn(moto_session: None) -> str:
    sns = boto3.client("sns", region_name=_REGION)
    return sns.create_topic(Name="SentinelCriticalFindings-e2e")["TopicArn"]


@pytest.fixture
def evidence_client(evidence_bucket: str) -> EvidenceClient:
    fake_kms = _FakeKms()
    s3 = boto3.client("s3", region_name=_REGION)
    return EvidenceClient(
        bucket=evidence_bucket,
        kms_key_arn=_KMS_KEY_ARN,
        s3_client=s3,
        signer=KmsSigner(key_arn=_KMS_KEY_ARN, client=fake_kms),  # type: ignore[arg-type]
        verifier=KmsVerifier(client=fake_kms),  # type: ignore[arg-type]
    )


@pytest.fixture
def sns_client(critical_findings_topic_arn: str) -> SnsClient:
    return SnsClient(
        topic_arn=critical_findings_topic_arn,
        client=boto3.client("sns", region_name=_REGION),
    )


@dataclass
class PostTurnHarness:
    """Bundles the real `PrimePostTurnProcessor` with the moto-backed
    clients underneath it, plus a `MagicMock` Security Hub client -- see
    module docstring for why that one boundary is mocked.
    """

    processor: PrimePostTurnProcessor
    decisions: DecisionsClient
    idempotency: IdempotencyClient
    evidence: EvidenceClient
    sns: SnsClient
    security_hub: MagicMock


@pytest.fixture
def post_turn_harness(
    decisions_table: Table,
    idempotency_table: Table,
    evidence_client: EvidenceClient,
    sns_client: SnsClient,
    moto_breaker: BreakerAccessor,
) -> PostTurnHarness:
    decisions = DecisionsClient(table=decisions_table, breaker=moto_breaker)
    idempotency = IdempotencyClient(table=idempotency_table, breaker=moto_breaker)
    security_hub = MagicMock()
    processor = PrimePostTurnProcessor(
        idempotency=idempotency,
        decisions=decisions,
        evidence=evidence_client,
        security_hub=security_hub,
        sns=sns_client,
    )
    return PostTurnHarness(
        processor=processor,
        decisions=decisions,
        idempotency=idempotency,
        evidence=evidence_client,
        sns=sns_client,
        security_hub=security_hub,
    )


@pytest.fixture
def revocations_client(
    revocations_table: Table, moto_breaker: BreakerAccessor
) -> RevocationsClient:
    return RevocationsClient(table=revocations_table, breaker=moto_breaker)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
