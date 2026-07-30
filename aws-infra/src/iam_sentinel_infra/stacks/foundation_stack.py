"""DDB tables, the OpenSearch Serverless vector collection, S3 buckets,
SQS queues, and SNS topics for Sentinel's data plane (phase-02). See
ADR 0005 for the key-attribute convention, the full 14-table count, why
the OSS index bootstrap signs its own SigV4 requests instead of depending
on `opensearchpy`, and which acceptance criteria are deferred pending a
real AWS dev account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import CustomResource, Duration, RemovalPolicy, Stack
from aws_cdk import aws_backup as backup
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_opensearchserverless as oss
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sqs as sqs
from cdk_nag import NagSuppressions

from iam_sentinel_infra.constructs.signed_object_lock_bucket import SignedObjectLockBucket

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.security_stack import SecurityStack

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"
_COLLECTION_NAME = "sentinel-episodic-vector"


@dataclass(frozen=True)
class _Gsi:
    index_name: str
    pk: str
    sk: str


@dataclass(frozen=True)
class _TableSpec:
    name: str
    pk: str
    sk: str | None = None
    gsis: tuple[_Gsi, ...] = field(default_factory=tuple)
    ttl_attribute: str | None = None
    contributor_insights: bool = False


_TABLES: tuple[_TableSpec, ...] = (
    _TableSpec(
        "SentinelFindings",
        pk="account_id#feature_id",
        sk="finding_id#detected_at",
        gsis=(
            _Gsi("severity-index", pk="severity", sk="detected_at"),
            _Gsi("feature-status-index", pk="feature_id#status", sk="detected_at"),
        ),
        ttl_attribute="expires_at",
        contributor_insights=True,
    ),
    _TableSpec(
        "SentinelDecisions",
        pk="principal",
        sk="decided_at",
        gsis=(_Gsi("correlation-index", pk="correlation_id", sk="decided_at"),),
        contributor_insights=True,
    ),
    _TableSpec("SentinelDecisionsInFlight", pk="correlation_id", ttl_attribute="expires_at"),
    _TableSpec(
        "SentinelMemoryEpisodic",
        pk="principal",
        sk="decided_at",
        gsis=(
            _Gsi("account-index", pk="account_id", sk="decided_at"),
            _Gsi("feature-index", pk="feature_id", sk="decided_at"),
            _Gsi("subject-index", pk="subject_arn", sk="detected_at"),
        ),
        ttl_attribute="expires_at",
    ),
    _TableSpec(
        "SentinelMemorySemantic",
        pk="entity_kind",
        sk="entity_key",
        gsis=(_Gsi("related-index", pk="related_entity", sk="entity_key"),),
    ),
    _TableSpec("SentinelMemoryProcedural", pk="pattern_kind", sk="pattern_hash", ttl_attribute="expires_at"),
    _TableSpec(
        "SentinelBudget",
        pk="correlation_id",
        sk="ulid",
        gsis=(_Gsi("principal-index", pk="principal", sk="ymd"),),
        ttl_attribute="expires_at",
        contributor_insights=True,
    ),
    _TableSpec("SentinelBreakers", pk="breaker_name"),
    _TableSpec("SentinelPolicies", pk="org_id", sk="policy_arn", ttl_attribute="expires_at"),
    _TableSpec("SentinelSLRs", pk="service_principal"),
    _TableSpec(
        "SentinelRevocations",
        pk="account_id",
        sk="role_arn",
        gsis=(_Gsi("correlation-index", pk="correlation_id", sk="attached_at"),),
        ttl_attribute="ttl_expires_at",
    ),
    _TableSpec(
        "SentinelFaults",
        pk="correlation_id",
        sk="detected_at",
        gsis=(_Gsi("fault-class-index", pk="fault_class", sk="detected_at"),),
        ttl_attribute="expires_at",
    ),
    _TableSpec(
        "SentinelDivergence",
        pk="correlation_id",
        sk="detected_at",
        gsis=(_Gsi("feature-divergence-index", pk="feature_id", sk="divergence_kind"),),
        ttl_attribute="expires_at",
    ),
    _TableSpec("SentinelIdempotency", pk="idempotency_key", ttl_attribute="expires_at"),
)


class FoundationStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        security: SecurityStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.security = security

        self.tables = {spec.name: self._build_table(spec) for spec in _TABLES}
        self._build_backup_plan()
        self._build_opensearch_collection(stage_config)
        self._build_buckets(stage_config)
        self._build_queues()
        self.topics = self._build_topics()

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": "Lambda runtime pinned to PYTHON_3_12 explicitly across every construct in this repo.",
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole is CDK's default Lambda execution role "
                        "addition (CloudWatch Logs only, scoped to the function's own log group); "
                        "AWSBackupServiceRolePolicyForBackup is CDK's default AWS Backup selection "
                        "role, an AWS managed policy specifically designed for that service role."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup",
                    ],
                },
                {
                    "id": "HIPAA.Security-IAMNoInlinePolicy",
                    "reason": (
                        "CDK's auto-generated DefaultPolicy grants (aoss:APIAccessAll scoped "
                        "to one collection ARN); splitting it into a managed policy adds "
                        "indirection without changing the effective grant."
                    ),
                },
                {
                    "id": "HIPAA.Security-LambdaInsideVPC",
                    "reason": (
                        "docs/ARCHITECTURE.md §Networking: IAM Sentinel is deliberately "
                        "VPC-less across the whole platform."
                    ),
                },
                {
                    "id": "HIPAA.Security-S3BucketReplicationEnabled",
                    "reason": (
                        "Single-region deployment by design (docs/ARCHITECTURE.md defines no "
                        "multi-region topology); cross-region replication would double "
                        "storage cost and region count for a DR posture not yet scoped."
                    ),
                },
                {
                    "id": "HIPAA.Security-S3DefaultEncryptionKMS",
                    "reason": (
                        "AccessLogsBucket is the target for S3 server access log delivery, "
                        "which AWS does not support against a KMS (SSE-KMS) destination "
                        "bucket -- only SSE-S3. This is the one bucket that must stay off KMS."
                    ),
                },
            ],
        )

    def _build_table(self, spec: _TableSpec) -> dynamodb.Table:
        table = dynamodb.Table(
            self,
            spec.name,
            table_name=f"{spec.name}-{self.stage_config.stage}",
            partition_key=dynamodb.Attribute(name=spec.pk, type=dynamodb.AttributeType.STRING),
            sort_key=(
                dynamodb.Attribute(name=spec.sk, type=dynamodb.AttributeType.STRING) if spec.sk else None
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.security.data_key,
            point_in_time_recovery=True,
            deletion_protection=True,
            time_to_live_attribute=spec.ttl_attribute,
            contributor_insights_enabled=spec.contributor_insights,
            removal_policy=RemovalPolicy.RETAIN,
        )
        for gsi in spec.gsis:
            table.add_global_secondary_index(
                index_name=gsi.index_name,
                partition_key=dynamodb.Attribute(name=gsi.pk, type=dynamodb.AttributeType.STRING),
                sort_key=dynamodb.Attribute(name=gsi.sk, type=dynamodb.AttributeType.STRING),
            )
        return table

    def _build_backup_plan(self) -> None:
        """Org-wide AWS Backup plan covering every Sentinel DDB table,
        promised in ADR 0003 once this phase landed the rest of them."""
        vault = backup.BackupVault(
            self, "BackupVault", encryption_key=self.security.data_key, removal_policy=RemovalPolicy.RETAIN
        )
        plan = backup.BackupPlan(
            self,
            "BackupPlan",
            backup_vault=vault,
            backup_plan_rules=[
                backup.BackupPlanRule.daily(),
                backup.BackupPlanRule.monthly1_year(),
            ],
        )
        plan.add_selection(
            "BackupSelection",
            resources=[backup.BackupResource.from_dynamo_db_table(t) for t in self.tables.values()],
        )

    def _build_opensearch_collection(self, stage_config: StageConfig) -> None:
        encryption_policy = oss.CfnSecurityPolicy(
            self,
            "OssEncryptionPolicy",
            name=f"{_COLLECTION_NAME}-enc-{stage_config.stage}"[:32],
            type="encryption",
            policy=self.to_json_string(
                {
                    "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{_COLLECTION_NAME}"]}],
                    "AWSOwnedKey": False,
                    "KmsARN": self.security.data_key.key_arn,
                }
            ),
        )
        network_policy = oss.CfnSecurityPolicy(
            self,
            "OssNetworkPolicy",
            name=f"{_COLLECTION_NAME}-net-{stage_config.stage}"[:32],
            type="network",
            policy=self.to_json_string(
                [
                    {
                        "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{_COLLECTION_NAME}"]}],
                        "AllowFromPublic": True,
                    }
                ]
            ),
        )

        self.collection = oss.CfnCollection(
            self, "EpisodicVectorCollection", name=_COLLECTION_NAME, type="VECTORSEARCH"
        )
        self.collection.add_dependency(encryption_policy)
        self.collection.add_dependency(network_policy)

        access_policy = oss.CfnAccessPolicy(
            self,
            "OssAccessPolicy",
            name=f"{_COLLECTION_NAME}-access-{stage_config.stage}"[:32],
            type="data",
            policy=self.to_json_string(
                [
                    {
                        "Rules": [
                            {
                                "ResourceType": "collection",
                                "Resource": [f"collection/{_COLLECTION_NAME}"],
                                "Permission": ["aoss:*"],
                            },
                            {
                                "ResourceType": "index",
                                "Resource": [f"index/{_COLLECTION_NAME}/*"],
                                "Permission": ["aoss:*"],
                            },
                        ],
                        # Specialist/memory-syncer Lambda roles are added here once
                        # aws-infra phase-04/agents phase-14 create them.
                        "Principal": [f"arn:aws:iam::{stage_config.account_id}:root"],
                    }
                ]
            ),
        )
        access_policy.node.add_dependency(self.collection)

        self._build_oss_index_bootstrap()

    def _build_oss_index_bootstrap(self) -> None:
        dead_letter_queue = sqs.Queue(
            self, "OssBootstrapDlq", retention_period=Duration.days(14), enforce_ssl=True
        )
        bootstrap_fn = lambda_.Function(
            self,
            "OssIndexBootstrapFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "oss_index_bootstrap")),
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=2,
            dead_letter_queue=dead_letter_queue,
        )
        bootstrap_fn.add_to_role_policy(
            iam.PolicyStatement(actions=["aoss:APIAccessAll"], resources=[self.collection.attr_arn])
        )

        CustomResource(
            self,
            "OssIndexBootstrap",
            service_token=bootstrap_fn.function_arn,
            properties={"CollectionEndpoint": self.collection.attr_collection_endpoint},
        )

    def _build_buckets(self, stage_config: StageConfig) -> None:
        access_logs = s3.Bucket(
            self,
            "AccessLogsBucket",
            bucket_name=f"sentinel-access-logs-{stage_config.stage}-{stage_config.account_id}",
            # SSE-S3, not KMS: S3 server access log delivery does not support
            # a KMS-encrypted (SSE-KMS) destination bucket.
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.evidence_bucket = SignedObjectLockBucket(
            self,
            "Evidence",
            kms_key=self.security.data_key,
            retention_years=7,
            access_log_bucket=access_logs,
        ).bucket

        self.reports_bucket = self._standard_bucket(
            "Reports",
            stage_config,
            access_logs,
            lifecycle_rules=[
                s3.LifecycleRule(
                    transitions=[
                        s3.Transition(storage_class=s3.StorageClass.INFREQUENT_ACCESS, transition_after=Duration.days(90)),
                        s3.Transition(storage_class=s3.StorageClass.GLACIER, transition_after=Duration.days(365)),
                    ]
                )
            ],
        )
        self.kb_source_bucket = self._standard_bucket(
            "KbSource",
            stage_config,
            access_logs,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(90))],
        )
        self.kb_manifest_bucket = self._standard_bucket(
            "KbManifest",
            stage_config,
            access_logs,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(90))],
        )
        self.athena_results_bucket = self._standard_bucket(
            "AthenaResults",
            stage_config,
            access_logs,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(7))],
        )

    def _standard_bucket(
        self,
        construct_id: str,
        stage_config: StageConfig,
        access_logs: s3.IBucket,
        *,
        lifecycle_rules: list[s3.LifecycleRule],
    ) -> s3.Bucket:
        bucket_name = f"sentinel-{construct_id.lower()}-{stage_config.stage}-{stage_config.account_id}"
        return s3.Bucket(
            self,
            construct_id,
            bucket_name=bucket_name,
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.security.data_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            server_access_logs_bucket=access_logs,
            server_access_logs_prefix=f"{construct_id.lower()}/",
            lifecycle_rules=lifecycle_rules,
            removal_policy=RemovalPolicy.RETAIN,
        )

    def _build_queues(self) -> None:
        dlq = sqs.Queue(
            self,
            "SessionKillDlq",
            fifo=True,
            queue_name="SessionKillQueue-DLQ.fifo",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.security.data_key,
            enforce_ssl=True,
        )
        self.session_kill_queue = sqs.Queue(
            self,
            "SessionKillQueue",
            fifo=True,
            queue_name="SessionKillQueue.fifo",
            content_based_deduplication=False,
            retention_period=Duration.days(4),
            visibility_timeout=Duration.seconds(30),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.security.data_key,
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

    def _build_topics(self) -> dict[str, sns.Topic]:
        # SentinelSecurity is deliberately excluded here: aws-infra phase-01
        # (SecurityStack) already created it for the break-glass alarm, and
        # SNS topic names must be unique per account+region -- creating it
        # again would collide at deploy time. See ADR 0005.
        names = (
            "SentinelCriticalFindings",
            "SentinelEmergencyRevocations",
            "SentinelWeeklyReports",
            "SentinelCostAnomaly",
            "SentinelOps",
        )
        topics = {
            name: sns.Topic(self, name, topic_name=name, master_key=self.security.data_key)
            for name in names
        }
        topics["SentinelSecurity"] = self.security.security_topic
        return topics
