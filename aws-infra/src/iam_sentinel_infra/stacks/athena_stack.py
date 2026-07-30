"""Glue Data Catalog table + Athena workgroup over the org CloudTrail bucket
(phase-03). F3 (Data Event Enricher), F4 (SCP Impact Analyst), and F6
(Shadow Guard, offline aggregation only) query the `sentinel` workgroup
once their Lambdas exist in `LambdaStack` (aws-infra phase-04) -- that
stack already declares `athena` as an upstream dependency in
`app_factory.build_app` and will call `grant_query_access` /
`grant_curate_write` on this stack's public API once those roles land.

See ADR 0009 for the workgroup-name discrepancy between this phase's spec
(`sentinel`) and `agents/docs/phase-04-data-event-enricher.txt` (`sentinel-f3`),
and for the three acceptance criteria deferred pending a real AWS dev
account + a populated org trail.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import CustomResource, Duration, Stack
from aws_cdk import aws_athena as athena
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sqs as sqs
from cdk_nag import NagSuppressions

from iam_sentinel_infra.constructs.sentinel_lambda import LAMBDA_ASSET_EXCLUDES

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.foundation_stack import FoundationStack

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"

DATABASE_NAME = "sentinel_cloudtrail"
RAW_TABLE_NAME = "cloudtrail_logs"
CURATED_TABLE_NAME = "writes_curated"
WORKGROUP_NAME = "sentinel"
_BYTES_SCANNED_CUTOFF = 107_374_182_400  # 100 GB, per phase-03 spec §4.
_CURATED_PREFIX = "athena-curated/writes_curated/"

# Mirrors the AWS-published CloudTrail Athena table schema exactly (phase-03
# §3: "Table matches the CloudTrail schema exactly"). Kept as an ordered
# tuple, not a dict, because Glue column order is part of the table's
# on-disk contract for the JSON SerDe.
CLOUDTRAIL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("eventversion", "string"),
    (
        "useridentity",
        "struct<type:string,principalid:string,arn:string,accountid:string,"
        "invokedby:string,accesskeyid:string,username:string,"
        "sessioncontext:struct<attributes:struct<mfaauthenticated:string,"
        "creationdate:string>,sessionissuer:struct<type:string,"
        "principalid:string,arn:string,accountid:string,username:string>>>",
    ),
    ("eventtime", "string"),
    ("eventsource", "string"),
    ("eventname", "string"),
    ("awsregion", "string"),
    ("sourceipaddress", "string"),
    ("useragent", "string"),
    ("errorcode", "string"),
    ("errormessage", "string"),
    ("requestparameters", "string"),
    ("responseelements", "string"),
    ("additionaleventdata", "string"),
    ("requestid", "string"),
    ("eventid", "string"),
    ("resources", "array<struct<arn:string,accountid:string,type:string>>"),
    ("eventtype", "string"),
    ("apiversion", "string"),
    ("readonly", "string"),
    ("recipientaccountid", "string"),
    ("serviceeventdetails", "string"),
    ("sharedeventid", "string"),
    ("vpcendpointid", "string"),
    (
        "tlsdetails",
        "struct<tlsversion:string,ciphersuite:string,clientprovidedhostheader:string>",
    ),
)


class AthenaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        foundation: FoundationStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.foundation = foundation
        self._data_key = foundation.security.data_key

        self.database = self._build_database()
        self.raw_table = self._build_raw_table(stage_config)
        self.workgroup = self._build_workgroup()
        self._bootstrap = self._build_bootstrap_custom_resource(stage_config)
        self.curate_function = self._build_curate_function(stage_config)

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole is CDK's default Lambda execution role "
                        "addition (CloudWatch Logs only, scoped to the function's own log group)."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Remaining wildcards are S3 object-level suffixes (`/*` under the "
                        "results bucket or curated-writes prefix this stack was granted "
                        "access to -- FoundationStack owns both buckets, cross-stack, so "
                        "the exact resource token cdk-nag reports depends on CloudFormation's "
                        "generated Fn::ImportValue export name, not something this stack "
                        "controls) and the fixed action set `Key.grant_encrypt_decrypt` "
                        "always emits (kms:GenerateDataKey*, kms:ReEncrypt*) -- both are "
                        "CDK's own least-privilege grant helpers operating on Sentinel-owned "
                        "resources, not hand-rolled wildcards."
                    ),
                },
                {
                    "id": "HIPAA.Security-IAMNoInlinePolicy",
                    "reason": (
                        "CDK's auto-generated DefaultPolicy grants (Athena/Glue/S3/KMS "
                        "actions scoped to this stack's own resources); splitting each "
                        "into a managed policy adds indirection without changing the "
                        "effective grant."
                    ),
                },
                {
                    "id": "HIPAA.Security-LambdaInsideVPC",
                    "reason": (
                        "docs/ARCHITECTURE.md §Networking: IAM Sentinel is deliberately "
                        "VPC-less across the whole platform."
                    ),
                },
            ],
        )

    def _build_database(self) -> glue.CfnDatabase:
        return glue.CfnDatabase(
            self,
            "CloudtrailDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(name=DATABASE_NAME),
        )

    def _build_raw_table(self, stage_config: StageConfig) -> glue.CfnTable:
        trail_bucket = stage_config.org_trail_bucket_name
        columns = [
            glue.CfnTable.ColumnProperty(name=name, type=type_)
            for name, type_ in CLOUDTRAIL_COLUMNS
        ]

        table = glue.CfnTable(
            self,
            "CloudtrailLogsTable",
            catalog_id=self.account,
            database_name=DATABASE_NAME,
            table_input=glue.CfnTable.TableInputProperty(
                name=RAW_TABLE_NAME,
                table_type="EXTERNAL_TABLE",
                partition_keys=[
                    glue.CfnTable.ColumnProperty(name="account_id", type="string"),
                    glue.CfnTable.ColumnProperty(name="region", type="string"),
                    glue.CfnTable.ColumnProperty(name="year", type="string"),
                    glue.CfnTable.ColumnProperty(name="month", type="string"),
                    glue.CfnTable.ColumnProperty(name="day", type="string"),
                ],
                storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                    columns=columns,
                    location=f"s3://{trail_bucket}/AWSLogs/",
                    input_format="com.amazon.emr.cloudtrail.CloudTrailInputFormat",
                    output_format="org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                    serde_info=glue.CfnTable.SerdeInfoProperty(
                        serialization_library="com.amazon.emr.hive.serde.CloudTrailSerde"
                    ),
                ),
                parameters={
                    "projection.enabled": "true",
                    "projection.account_id.type": "injected",
                    "projection.region.type": "injected",
                    "projection.year.type": "integer",
                    "projection.year.range": "2020,2035",
                    "projection.month.type": "integer",
                    "projection.month.range": "1,12",
                    "projection.month.digits": "2",
                    "projection.day.type": "integer",
                    "projection.day.range": "1,31",
                    "projection.day.digits": "2",
                    "storage.location.template": (
                        f"s3://{trail_bucket}/AWSLogs/${{account_id}}/CloudTrail/${{region}}/${{year}}/${{month}}/${{day}}/"
                    ),
                },
            ),
        )
        table.add_dependency(self.database)
        return table

    def _build_workgroup(self) -> athena.CfnWorkGroup:
        return athena.CfnWorkGroup(
            self,
            "Workgroup",
            name=WORKGROUP_NAME,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
                bytes_scanned_cutoff_per_query=_BYTES_SCANNED_CUTOFF,
                engine_version=athena.CfnWorkGroup.EngineVersionProperty(
                    selected_engine_version="Athena engine version 3"
                ),
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{self.foundation.athena_results_bucket.bucket_name}/",
                    encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                        encryption_option="SSE_KMS",
                        kms_key=self._data_key.key_arn,
                    ),
                ),
            ),
        )

    def _build_bootstrap_custom_resource(self, stage_config: StageConfig) -> _AthenaBootstrap:
        return _AthenaBootstrap(
            self,
            "Bootstrap",
            workgroup_name=self.workgroup.name,
            database_name=DATABASE_NAME,
            curated_table_name=CURATED_TABLE_NAME,
            curated_location=f"s3://{self.foundation.reports_bucket.bucket_name}/{_CURATED_PREFIX}",
            trail_bucket_name=stage_config.org_trail_bucket_name,
            data_key_arn=self._data_key.key_arn,
            account=self.account,
            region=self.region,
            results_bucket_arn=self.foundation.athena_results_bucket.bucket_arn,
            reports_bucket_arn=self.foundation.reports_bucket.bucket_arn,
        )

    def _build_curate_function(self, stage_config: StageConfig) -> lambda_.Function:
        """Hourly Lambda `athena_curate_writes` (phase-03 §5): CTAS/INSERT over
        the last hour of raw CloudTrail write events into the Iceberg
        `writes_curated` table -- substantially less scan volume for F4/F6
        than querying raw logs directly."""
        dlq = sqs.Queue(self, "CurateDlq", retention_period=Duration.days(14), enforce_ssl=True)
        function = lambda_.Function(
            self,
            "CurateFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "athena_curate_writes"), exclude=LAMBDA_ASSET_EXCLUDES),
            timeout=Duration.minutes(5),
            reserved_concurrent_executions=1,
            dead_letter_queue=dlq,
            environment={
                "SENTINEL_STAGE": stage_config.stage,
                "ATHENA_WORKGROUP": WORKGROUP_NAME,
                "ATHENA_DATABASE": DATABASE_NAME,
                "ATHENA_RAW_TABLE": RAW_TABLE_NAME,
                "ATHENA_CURATED_TABLE": CURATED_TABLE_NAME,
            },
        )
        self.grant_query_access(function, write=True)

        events.Rule(
            self,
            "CurateSchedule",
            schedule=events.Schedule.rate(Duration.hours(1)),
            targets=[targets.LambdaFunction(function)],
        )
        return function

    def grant_query_access(self, grantee: iam.IGrantable, *, write: bool = False) -> None:
        """Grants a Lambda execution role query access to the `sentinel`
        workgroup + `sentinel_cloudtrail` catalog. `LambdaStack` (phase-04)
        calls this for F3/F4/F6's roles once they exist -- see the module
        docstring. `write=True` additionally allows writing into the
        Iceberg curated table (only the curate Lambda needs this today)."""
        iam.Grant.add_to_principal(
            grantee=grantee,
            actions=[
                "athena:StartQueryExecution",
                "athena:GetQueryExecution",
                "athena:GetQueryResults",
                "athena:StopQueryExecution",
                "athena:GetWorkGroup",
            ],
            resource_arns=[
                f"arn:aws:athena:{self.region}:{self.account}:workgroup/{WORKGROUP_NAME}"
            ],
        )
        catalog_actions = [
            "glue:GetDatabase",
            "glue:GetTable",
            "glue:GetTables",
            "glue:GetPartition",
            "glue:GetPartitions",
        ]
        if write:
            catalog_actions += ["glue:CreateTable", "glue:UpdateTable", "glue:BatchCreatePartition"]
        iam.Grant.add_to_principal(
            grantee=grantee,
            actions=catalog_actions,
            resource_arns=[
                f"arn:aws:glue:{self.region}:{self.account}:catalog",
                f"arn:aws:glue:{self.region}:{self.account}:database/{DATABASE_NAME}",
                f"arn:aws:glue:{self.region}:{self.account}:table/{DATABASE_NAME}/{RAW_TABLE_NAME}",
                f"arn:aws:glue:{self.region}:{self.account}:table/{DATABASE_NAME}/{CURATED_TABLE_NAME}",
            ],
        )
        result_actions = ["s3:GetBucketLocation", "s3:GetObject", "s3:ListBucket", "s3:PutObject"]
        iam.Grant.add_to_principal(
            grantee=grantee,
            actions=result_actions,
            resource_arns=[
                self.foundation.athena_results_bucket.bucket_arn,
                f"{self.foundation.athena_results_bucket.bucket_arn}/*",
            ],
        )
        if write:
            iam.Grant.add_to_principal(
                grantee=grantee,
                actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"],
                resource_arns=[
                    self.foundation.reports_bucket.bucket_arn,
                    f"{self.foundation.reports_bucket.bucket_arn}/{_CURATED_PREFIX}*",
                ],
            )
        # Reads to the org trail bucket require its bucket policy (in the org
        # CloudTrail account) to allow this account's principals -- that is
        # an out-of-repo, cross-account grant this stack cannot create. See
        # ADR 0009.
        self._data_key.grant_encrypt_decrypt(grantee)


class _AthenaBootstrap:
    """Idempotent one-shot setup run by a CloudFormation custom resource
    (phase-03 §5, §9 risk mitigation): verifies the org trail bucket is
    readable at deploy time (fail early, per §9) and creates the Iceberg
    `writes_curated` table via an Athena `CREATE TABLE ... WITH
    (table_type='ICEBERG', ...)` statement if it doesn't already exist.

    Iceberg table metadata (`metadata.json` + manifest lists) can only be
    bootstrapped by an engine that understands the Iceberg spec -- Athena
    itself -- so, unlike `CloudtrailLogsTable` above, this table cannot be
    declared as a plain `AWS::Glue::Table` resource. See ADR 0009.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        workgroup_name: str,
        database_name: str,
        curated_table_name: str,
        curated_location: str,
        trail_bucket_name: str,
        data_key_arn: str,
        account: str,
        region: str,
        results_bucket_arn: str,
        reports_bucket_arn: str,
    ) -> None:
        self.dead_letter_queue = sqs.Queue(
            scope, f"{construct_id}Dlq", retention_period=Duration.days(14), enforce_ssl=True
        )
        self.handler = lambda_.Function(
            scope,
            f"{construct_id}Handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "athena_bootstrap"), exclude=LAMBDA_ASSET_EXCLUDES),
            timeout=Duration.minutes(5),
            reserved_concurrent_executions=1,
            dead_letter_queue=self.dead_letter_queue,
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                ],
                resources=[f"arn:aws:athena:{region}:{account}:workgroup/{workgroup_name}"],
            )
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["glue:GetDatabase"],
                resources=[f"arn:aws:glue:{region}:{account}:database/{database_name}"],
            )
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                # CreateTable's IAM authorization target is the table name being
                # created, even though it doesn't exist yet -- unlike S3, Glue table
                # ARNs are addressable pre-creation, so no "*" is needed here.
                actions=["glue:GetTable", "glue:CreateTable"],
                resources=[
                    f"arn:aws:glue:{region}:{account}:catalog",
                    f"arn:aws:glue:{region}:{account}:table/{database_name}/{curated_table_name}",
                ],
            )
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                # `s3:HeadBucket` (the API call `_check_trail_bucket_readable` makes) is
                # authorized by the `s3:ListBucket` IAM action per AWS's action-to-permission
                # mapping for S3 -- there is no separate `s3:HeadBucket` IAM action.
                actions=["s3:ListBucket"],
                resources=[f"arn:aws:s3:::{trail_bucket_name}"],
            )
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetBucketLocation", "s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                resources=[
                    results_bucket_arn,
                    f"{results_bucket_arn}/*",
                    reports_bucket_arn,
                    f"{reports_bucket_arn}/{_CURATED_PREFIX}*",
                ],
            )
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["kms:GenerateDataKey", "kms:Decrypt"], resources=[data_key_arn]
            )
        )

        self.resource = CustomResource(
            scope,
            construct_id,
            service_token=self.handler.function_arn,
            properties={
                "WorkgroupName": workgroup_name,
                "DatabaseName": database_name,
                "CuratedTableName": curated_table_name,
                "CuratedLocation": curated_location,
                "TrailBucketName": trail_bucket_name,
            },
        )
