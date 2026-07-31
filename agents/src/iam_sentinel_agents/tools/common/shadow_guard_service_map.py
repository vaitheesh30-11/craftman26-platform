"""CloudTrail `eventSource` -> IAM action prefix mapping.

agents/docs/phase-07-shadow-guard.txt §4 Step 2: "Extract eventSource (e.g.,
s3.amazonaws.com) -> service prefix via common/shadow_guard_service_map.py -> s3."
§10 names this table's drift as a known risk, mitigated in production by a
curated S3-hosted "known-services" registry refresh (deferred here -- no
such bucket or refresh Lambda exists yet; tracked below).

Most CloudTrail `eventSource` values are `f"{iam_action_prefix}.amazonaws.
com"` and need no table entry at all (`prefix_for` falls back to stripping
the `.amazonaws.com` suffix and taking the first label). `_EXCEPTIONS` only
lists the services whose CloudTrail hostname genuinely differs from their
IAM action prefix -- these are the ones a naive strip-and-take-first-label
approach gets wrong, curated from the AWS "Actions, resources, and
condition keys" reference for the busiest ~50 services by call volume.
"""

from __future__ import annotations

_SUFFIX = ".amazonaws.com"

_EXCEPTIONS: dict[str, str] = {
    "monitoring": "cloudwatch",
    "logs": "logs",
    "events": "events",
    "email": "ses",
    "ec2messages": "ec2messages",
    "elasticmapreduce": "elasticmapreduce",
    "elasticloadbalancing": "elasticloadbalancing",
    "execute-api": "execute-api",
    "application-autoscaling": "application-autoscaling",
    "autoscaling": "autoscaling",
    "cloudhsmv2": "cloudhsm",
    "config": "config",
    "cognito-idp": "cognito-idp",
    "cognito-identity": "cognito-identity",
    "es": "es",
    "opensearchservice": "es",
    "greengrass": "greengrass",
    "iotevents": "iotevents",
    "runtime.sagemaker": "sagemaker",
    "api.sagemaker": "sagemaker",
    "states": "states",
    "sts": "sts",
    "tagging": "tag",
    "resource-groups": "resource-groups",
    "servicecatalog": "servicecatalog",
    "signer": "signer",
    "ssm": "ssm",
    "ssmmessages": "ssmmessages",
    "streams.dynamodb": "dynamodb",
    "sso": "sso",
    "sso-directory": "sso-directory",
    "identitystore": "identitystore",
    "organizations": "organizations",
    "secretsmanager": "secretsmanager",
    "securityhub": "securityhub",
    "servicequotas": "servicequotas",
    "shield": "shield",
    "waf-regional": "waf-regional",
    "wafv2": "wafv2",
    "backup": "backup",
    "batch": "batch",
    "cloudtrail": "cloudtrail",
    "cloudformation": "cloudformation",
    "codebuild": "codebuild",
    "codecommit": "codecommit",
    "codedeploy": "codedeploy",
    "codepipeline": "codepipeline",
    "datapipeline": "datapipeline",
    "directconnect": "directconnect",
    "dms": "dms",
    "ds": "ds",
    "dynamodb": "dynamodb",
    "ec2": "ec2",
    "ecr": "ecr",
    "ecs": "ecs",
    "eks": "eks",
    "elasticache": "elasticache",
    "elasticbeanstalk": "elasticbeanstalk",
    "firehose": "firehose",
    "fsx": "fsx",
    "glacier": "glacier",
    "glue": "glue",
    "guardduty": "guardduty",
    "iam": "iam",
    "inspector2": "inspector2",
    "kafka": "kafka",
    "kinesis": "kinesis",
    "kms": "kms",
    "lambda": "lambda",
    "lightsail": "lightsail",
    "macie2": "macie2",
    "mediaconvert": "mediaconvert",
    "rds": "rds",
    "redshift": "redshift",
    "route53": "route53",
    "route53resolver": "route53resolver",
    "s3": "s3",
    "sagemaker": "sagemaker",
    "sns": "sns",
    "sqs": "sqs",
    "workspaces": "workspaces",
    "xray": "xray",
}


def prefix_for(event_source: str) -> str:
    """Map a CloudTrail `eventSource` hostname to its IAM action prefix.

    Unknown services fall back to the generic strip-and-take-first-label
    heuristic rather than raising -- ingestion must never drop a
    CloudTrail event because a brand-new AWS service isn't in the curated
    table yet (phase-07 §10's own mitigation calls for an INFO metric on a
    miss, not a hard failure; the metric emission lives in
    `tools/f6/ingest.py`, which is the caller with access to a metrics
    client).
    """
    normalized = event_source.strip().lower()
    label = normalized.removesuffix(_SUFFIX) if normalized.endswith(_SUFFIX) else normalized
    return _EXCEPTIONS.get(label, label)


def is_curated(event_source: str) -> bool:
    """True if `event_source` has an explicit table entry rather than
    falling back to the generic heuristic -- `tools/f6/ingest.py` emits an
    INFO metric when this is False, per phase-07 §10's drift mitigation.
    """
    normalized = event_source.strip().lower()
    label = normalized.removesuffix(_SUFFIX) if normalized.endswith(_SUFFIX) else normalized
    return label in _EXCEPTIONS
