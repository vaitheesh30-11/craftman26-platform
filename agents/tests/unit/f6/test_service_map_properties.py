"""Property test for `tools/common/shadow_guard_service_map.py`
(phase-07 §8: "Property (Hypothesis): service prefix mapping is complete
for the top 50 AWS services (fixture)").

`prefix_for` never raises and never returns an empty string for any
`eventSource`-shaped input; for the curated top-~50-by-call-volume
services it also returns the exact IAM action prefix (not just something
non-empty) -- that second, stronger property is what actually protects
against a `_EXCEPTIONS` typo silently regressing ingestion's `action`
string for a real, high-volume service.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from iam_sentinel_agents.tools.common import shadow_guard_service_map as svc_map

# Top ~50 AWS services by CloudTrail management-event call volume; hostname
# -> expected IAM action prefix. Doubles as the fixture phase-07 §8 asks for.
_TOP_50_SERVICES: dict[str, str] = {
    "s3.amazonaws.com": "s3",
    "ec2.amazonaws.com": "ec2",
    "iam.amazonaws.com": "iam",
    "sts.amazonaws.com": "sts",
    "kms.amazonaws.com": "kms",
    "lambda.amazonaws.com": "lambda",
    "dynamodb.amazonaws.com": "dynamodb",
    "logs.amazonaws.com": "logs",
    "monitoring.amazonaws.com": "cloudwatch",
    "events.amazonaws.com": "events",
    "sns.amazonaws.com": "sns",
    "sqs.amazonaws.com": "sqs",
    "cloudtrail.amazonaws.com": "cloudtrail",
    "cloudformation.amazonaws.com": "cloudformation",
    "organizations.amazonaws.com": "organizations",
    "secretsmanager.amazonaws.com": "secretsmanager",
    "ssm.amazonaws.com": "ssm",
    "ssmmessages.amazonaws.com": "ssmmessages",
    "ec2messages.amazonaws.com": "ec2messages",
    "autoscaling.amazonaws.com": "autoscaling",
    "application-autoscaling.amazonaws.com": "application-autoscaling",
    "elasticloadbalancing.amazonaws.com": "elasticloadbalancing",
    "rds.amazonaws.com": "rds",
    "redshift.amazonaws.com": "redshift",
    "ecs.amazonaws.com": "ecs",
    "ecr.amazonaws.com": "ecr",
    "eks.amazonaws.com": "eks",
    "elasticache.amazonaws.com": "elasticache",
    "elasticbeanstalk.amazonaws.com": "elasticbeanstalk",
    "glue.amazonaws.com": "glue",
    "athena.amazonaws.com": "athena",
    "firehose.amazonaws.com": "firehose",
    "kinesis.amazonaws.com": "kinesis",
    "es.amazonaws.com": "es",
    "opensearchservice.amazonaws.com": "es",
    "cognito-idp.amazonaws.com": "cognito-idp",
    "cognito-identity.amazonaws.com": "cognito-identity",
    "sso.amazonaws.com": "sso",
    "identitystore.amazonaws.com": "identitystore",
    "guardduty.amazonaws.com": "guardduty",
    "securityhub.amazonaws.com": "securityhub",
    "config.amazonaws.com": "config",
    "backup.amazonaws.com": "backup",
    "batch.amazonaws.com": "batch",
    "codebuild.amazonaws.com": "codebuild",
    "codecommit.amazonaws.com": "codecommit",
    "codedeploy.amazonaws.com": "codedeploy",
    "codepipeline.amazonaws.com": "codepipeline",
    "route53.amazonaws.com": "route53",
    "states.amazonaws.com": "states",
    "servicecatalog.amazonaws.com": "servicecatalog",
    "tagging.amazonaws.com": "tag",
}


def test_top_50_fixture_has_at_least_50_entries() -> None:
    assert len(_TOP_50_SERVICES) >= 50


@given(st.sampled_from(sorted(_TOP_50_SERVICES.items())))
def test_top_50_services_map_to_the_exact_expected_prefix(
    event_source_and_expected: tuple[str, str],
) -> None:
    event_source, expected_prefix = event_source_and_expected

    assert svc_map.prefix_for(event_source) == expected_prefix


@given(st.text(min_size=1, max_size=63, alphabet=st.characters(whitelist_categories=("Ll",))))
def test_prefix_for_never_raises_and_never_returns_empty(label: str) -> None:
    event_source = f"{label}.amazonaws.com"

    result = svc_map.prefix_for(event_source)

    assert isinstance(result, str)
    assert result != ""
