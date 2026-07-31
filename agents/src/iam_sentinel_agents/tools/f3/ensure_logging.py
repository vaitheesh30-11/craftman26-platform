"""data_event_ensure_logging — phase-04 §4 Step 1.

Calls boto3 CloudTrail APIs directly via `cross_account.assume()`'s
returned session -- the same deliberate exception to "boto3 only through
adapters/" that `tools/f1/scan.py` documents (no `adapters/` package wraps
CloudTrail read/write APIs, and this is a per-member-account read/write, not
a shared platform call).

This is F3's ONLY write action (phase-04 §4 Step 1's own note); it is
gated on `dry_run` exactly like `RemediationPlan.dry_run` gates every other
specialist's mutation, even though `data_event_ensure_logging` itself
predates `RemediationPlan` in this call chain -- the specialist prompt's
WORKFLOW step 2 is the caller that decides `dry_run=NOT consent_enable...`.
"""

from __future__ import annotations

from typing import Any, cast, TYPE_CHECKING

from iam_sentinel_agents.settings import settings
from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.common.runtime import sentinel_handler

if TYPE_CHECKING:
    import boto3
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_cloudtrail.client import CloudTrailClient
    from mypy_boto3_cloudtrail.type_defs import EventSelectorTypeDef

    from iam_sentinel_agents.contracts.common import FeatureID
    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

_S3_OBJECT_DATA_RESOURCE_TYPE = "AWS::S3::Object"
_S3_OBJECT_ALL_OBJECTS_SCOPE = "arn:aws:s3:::*/*"


def _selectors_already_cover_s3_objects(selectors: list[Any]) -> bool:
    for selector in selectors:
        for resource in selector.get("DataResources", []):
            if resource.get(
                "Type"
            ) == _S3_OBJECT_DATA_RESOURCE_TYPE and _S3_OBJECT_ALL_OBJECTS_SCOPE in resource.get(
                "Values", []
            ):
                return True
    return False


def ensure_logging(
    account_id: str,
    *,
    dry_run: bool = True,
    trail_name: str | None = None,
    feature_id: FeatureID = "F3",
    correlation_id: str = "data-event-ensure-logging",
    session: boto3.Session | None = None,
) -> dict[str, Any]:
    """Core logic, independent of the Bedrock Lambda envelope.

    `session` is an injection point for tests (an already-scoped moto
    session) -- production always goes through `cross_account.assume()`.
    """
    resolved_trail_name = trail_name or settings.org_trail_name
    boto_session = session or cross_account.assume(
        account_id, feature_id=feature_id, correlation_id=correlation_id
    )
    cloudtrail: CloudTrailClient = boto_session.client("cloudtrail")

    trail = cloudtrail.get_trail(Name=resolved_trail_name)["Trail"]
    trail_arn = trail["TrailARN"]
    selectors: list[Any] = list(
        cloudtrail.get_event_selectors(TrailName=resolved_trail_name).get("EventSelectors", [])
    )

    if _selectors_already_cover_s3_objects(selectors):
        return {"already_enabled": True, "enabled_now": False, "trail_arn": trail_arn}

    if not dry_run:
        new_selector: EventSelectorTypeDef = {
            "ReadWriteType": "All",
            "IncludeManagementEvents": True,
            "DataResources": [
                {"Type": _S3_OBJECT_DATA_RESOURCE_TYPE, "Values": [_S3_OBJECT_ALL_OBJECTS_SCOPE]}
            ],
        }
        cloudtrail.put_event_selectors(
            TrailName=resolved_trail_name,
            EventSelectors=cast("list[EventSelectorTypeDef]", [*selectors, new_selector]),
        )
        return {"already_enabled": False, "enabled_now": True, "trail_arn": trail_arn}

    return {"already_enabled": False, "enabled_now": False, "trail_arn": trail_arn}


@sentinel_handler(feature_id="F3", tool_name="data_event_ensure_logging")
def data_event_ensure_logging(
    invocation: ParsedInvocation, _context: LambdaContext
) -> dict[str, Any]:
    return ensure_logging(
        invocation.parameters["account_id"],
        dry_run=bool(invocation.parameters.get("dry_run", True)),
        correlation_id=invocation.correlation_id,
    )
