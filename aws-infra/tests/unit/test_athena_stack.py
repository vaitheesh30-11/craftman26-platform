"""Contract checks for AthenaStack (phase-03 §3, §4, §6): the Glue database
and CloudTrail table match the documented schema and partition-projection
config, the workgroup enforces the 100 GB scan cap and SSE-KMS encryption,
and `grant_query_access` grants exactly the actions a specialist Lambda
role needs (F3/F4/F6 land in aws-infra phase-04 -- see the module docstring
in `iam_sentinel_infra.stacks.athena_stack`).
"""

from __future__ import annotations

import json

from aws_cdk import App, Stack
from aws_cdk import aws_iam as iam
from aws_cdk.assertions import Match, Template

from iam_sentinel_infra.app_factory import build_app
from iam_sentinel_infra.config import load_stage_config
from iam_sentinel_infra.stacks.athena_stack import CLOUDTRAIL_COLUMNS, AthenaStack
from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
from iam_sentinel_infra.stacks.security_stack import SecurityStack

_FIXTURE_PATH = __file__.replace("test_athena_stack.py", "../fixtures/cloudtrail_schema.json")


def _athena_template() -> Template:
    app = build_app("dev")
    stack = app.node.find_child("SentinelAthena")
    return Template.from_stack(stack)


def test_glue_database_and_table_are_created_with_partition_projection() -> None:
    template = _athena_template()
    template.has_resource_properties(
        "AWS::Glue::Database", {"DatabaseInput": {"Name": "sentinel_cloudtrail"}}
    )
    template.has_resource_properties(
        "AWS::Glue::Table",
        {
            "DatabaseName": "sentinel_cloudtrail",
            "TableInput": Match.object_like(
                {
                    "Name": "cloudtrail_logs",
                    "PartitionKeys": [
                        {"Name": "account_id", "Type": "string"},
                        {"Name": "region", "Type": "string"},
                        {"Name": "year", "Type": "string"},
                        {"Name": "month", "Type": "string"},
                        {"Name": "day", "Type": "string"},
                    ],
                    "Parameters": Match.object_like(
                        {"projection.enabled": "true", "projection.year.range": "2020,2035"}
                    ),
                }
            ),
        },
    )


def test_table_columns_match_the_known_cloudtrail_schema_fixture() -> None:
    with open(_FIXTURE_PATH, encoding="utf-8") as handle:
        fixture = json.load(handle)
    fixture_columns = [(col["name"], col["type"]) for col in fixture["columns"]]
    assert list(CLOUDTRAIL_COLUMNS) == fixture_columns


def test_workgroup_enforces_the_100gb_scan_cap_and_sse_kms_encryption() -> None:
    template = _athena_template()
    template.has_resource_properties(
        "AWS::Athena::WorkGroup",
        {
            "Name": "sentinel",
            "WorkGroupConfiguration": {
                "EnforceWorkGroupConfiguration": True,
                "PublishCloudWatchMetricsEnabled": True,
                "BytesScannedCutoffPerQuery": 107_374_182_400,
                "EngineVersion": {"SelectedEngineVersion": "Athena engine version 3"},
                "ResultConfiguration": {"EncryptionConfiguration": {"EncryptionOption": "SSE_KMS"}},
            },
        },
    )


def test_curate_lambda_is_scheduled_hourly() -> None:
    template = _athena_template()
    template.has_resource_properties(
        "AWS::Events::Rule", {"ScheduleExpression": "rate(1 hour)", "State": "ENABLED"}
    )


def test_grant_query_access_grants_read_only_athena_and_glue_actions() -> None:
    app = App()
    security = SecurityStack(app, "TestSecurity", stage_config=load_stage_config("dev"))
    foundation = FoundationStack(
        app, "TestFoundation", stage_config=load_stage_config("dev"), security=security
    )
    athena = AthenaStack(
        app, "TestAthena", stage_config=load_stage_config("dev"), foundation=foundation
    )

    consumer_stack = Stack(app, "TestConsumer")
    role = iam.Role(
        consumer_stack, "SpecialistRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
    )
    athena.grant_query_access(role)

    template = Template.from_stack(consumer_stack)
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": Match.object_like(
                {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {"Action": Match.array_with(["athena:StartQueryExecution"])}
                            )
                        ]
                    )
                }
            )
        },
    )


def test_curate_lambda_role_additionally_gets_write_grants() -> None:
    template = _athena_template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": Match.object_like(
                {
                    "Statement": Match.array_with(
                        [Match.object_like({"Action": Match.array_with(["glue:CreateTable"])})]
                    )
                }
            )
        },
    )
