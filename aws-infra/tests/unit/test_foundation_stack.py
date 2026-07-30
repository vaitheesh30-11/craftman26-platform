"""Contract checks for the FoundationStack data plane (phase-02 §3, §8):
table count/keys match the adapters phase-05 inventory (see ADR 0005 for
the key-attribute convention), and the other data-plane primitives exist
with the properties phase-02 requires.
"""

from __future__ import annotations

from aws_cdk.assertions import Match, Template

from iam_sentinel_infra.app_factory import build_app

_TABLE_COUNT = 14


def _foundation_template() -> Template:
    app = build_app("dev")
    stack = app.node.find_child("SentinelFoundation")
    return Template.from_stack(stack)


def test_fourteen_tables_are_created() -> None:
    template = _foundation_template()
    template.resource_count_is("AWS::DynamoDB::Table", _TABLE_COUNT)


def test_findings_table_has_the_expected_keys_and_gsis() -> None:
    template = _foundation_template()
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "TableName": "SentinelFindings-dev",
            "KeySchema": [
                {"AttributeName": "account_id#feature_id", "KeyType": "HASH"},
                {"AttributeName": "finding_id#detected_at", "KeyType": "RANGE"},
            ],
            "GlobalSecondaryIndexes": Match.array_with(
                [
                    Match.object_like(
                        {
                            "IndexName": "severity-index",
                            "KeySchema": [
                                {"AttributeName": "severity", "KeyType": "HASH"},
                                {"AttributeName": "detected_at", "KeyType": "RANGE"},
                            ],
                        }
                    ),
                    Match.object_like(
                        {
                            "IndexName": "feature-status-index",
                            "KeySchema": [
                                {"AttributeName": "feature_id#status", "KeyType": "HASH"},
                                {"AttributeName": "detected_at", "KeyType": "RANGE"},
                            ],
                        }
                    ),
                ]
            ),
            "TimeToLiveSpecification": {"AttributeName": "expires_at", "Enabled": True},
        },
    )


def test_every_table_has_pitr_and_deletion_protection() -> None:
    template = _foundation_template()
    template.all_resources_properties(
        "AWS::DynamoDB::Table",
        {
            "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
            "DeletionProtectionEnabled": True,
            "SSESpecification": Match.object_like({"SSEEnabled": True}),
        },
    )


def test_session_kill_queue_is_a_fifo_queue_with_a_dlq() -> None:
    template = _foundation_template()
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "SessionKillQueue.fifo",
            "FifoQueue": True,
            "ContentBasedDeduplication": False,
            "RedrivePolicy": Match.object_like({"maxReceiveCount": 3}),
        },
    )


def test_five_new_sns_topics_are_created() -> None:
    template = _foundation_template()
    template.resource_count_is("AWS::SNS::Topic", 5)


def test_backup_plan_selects_all_tables() -> None:
    template = _foundation_template()
    selections = template.find_resources("AWS::Backup::BackupSelection")
    (selection,) = selections.values()
    resources = selection["Properties"]["BackupSelection"]["Resources"]
    assert len(resources) == _TABLE_COUNT
