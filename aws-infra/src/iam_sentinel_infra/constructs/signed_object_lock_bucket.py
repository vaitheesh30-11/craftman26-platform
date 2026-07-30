"""KMS-encrypted, Object-Lock S3 bucket for KMS-signed evidence (phase-00 §4).

Every write is content-addressed and signed before it lands here; this
construct only owns the storage-layer guarantees (immutability, encryption,
no public access) that the signature scheme depends on.
"""

from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct


class SignedObjectLockBucket(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        kms_key: kms.IKey,
        retention_years: int = 7,
        removal_policy: RemovalPolicy = RemovalPolicy.RETAIN,
    ) -> None:
        super().__init__(scope, construct_id)

        self.access_log_bucket = s3.Bucket(
            self,
            "AccessLogBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=removal_policy,
        )

        self.bucket = s3.Bucket(
            self,
            "Bucket",
            object_lock_enabled=True,
            object_lock_default_retention=s3.ObjectLockRetention.compliance(
                Duration.days(365 * retention_years)
            ),
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            server_access_logs_bucket=self.access_log_bucket,
            server_access_logs_prefix="access-logs/",
            removal_policy=removal_policy,
        )
