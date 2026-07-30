"""CloudFormation custom-resource Lambda owning the Bedrock Guardrail
lifecycle (aws-infra phase-01 §4, agents phase-11 §3). CloudFormation has
no native `AWS::Bedrock::Guardrail` resource, so Create/Update/Delete map
directly to `bedrock:CreateGuardrail` / `UpdateGuardrail` /
`DeleteGuardrail` + `CreateGuardrailVersion`.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import boto3

_bedrock = boto3.client("bedrock")

# CFN CustomResource property names are PascalCase; Bedrock's API wants
# camelCase. This is the one-to-one mapping between the two for every
# optional policy-config field agents phase-11 §3 lists.
_OPTIONAL_POLICY_FIELDS = (
    "topicPolicyConfig",
    "contentPolicyConfig",
    "sensitiveInformationPolicyConfig",
    "contextualGroundingPolicyConfig",
)


def _policy_kwargs(properties: dict[str, Any]) -> dict[str, Any]:
    policy_config = properties.get("PolicyConfig", {})
    return {field: policy_config[field] for field in _OPTIONAL_POLICY_FIELDS if field in policy_config}


def route_request(
    request_type: str,
    properties: dict[str, Any],
    physical_id: str | None,
) -> dict[str, Any]:
    """Pure dispatch over the three CFN RequestTypes. Kept separate from
    `handler` so it is unit-testable without CloudFormation's
    response-signaling protocol.
    """
    if request_type == "Create":
        created = _bedrock.create_guardrail(
            name=properties["GuardrailName"],
            blockedInputMessaging=properties["BlockedInputMessaging"],
            blockedOutputsMessaging=properties["BlockedOutputsMessaging"],
            **_policy_kwargs(properties),
        )
        version = _bedrock.create_guardrail_version(guardrailIdentifier=created["guardrailId"])
        return {
            "PhysicalResourceId": created["guardrailId"],
            "Data": {"GuardrailArn": created["guardrailArn"], "GuardrailVersion": version["version"]},
        }

    if request_type == "Update":
        if physical_id is None:
            raise ValueError("Update requested without a physical resource id")
        _bedrock.update_guardrail(
            guardrailIdentifier=physical_id,
            name=properties["GuardrailName"],
            blockedInputMessaging=properties["BlockedInputMessaging"],
            blockedOutputsMessaging=properties["BlockedOutputsMessaging"],
            **_policy_kwargs(properties),
        )
        version = _bedrock.create_guardrail_version(guardrailIdentifier=physical_id)
        return {"PhysicalResourceId": physical_id, "Data": {"GuardrailVersion": version["version"]}}

    if request_type == "Delete":
        if physical_id is not None:
            _bedrock.delete_guardrail(guardrailIdentifier=physical_id)
        return {"PhysicalResourceId": physical_id or "already-deleted"}

    raise ValueError(f"unsupported RequestType: {request_type!r}")


def handler(event: dict[str, Any], _context: object) -> None:
    try:
        result = route_request(
            event["RequestType"],
            event.get("ResourceProperties", {}),
            event.get("PhysicalResourceId"),
        )
        _send_response(
            event, "SUCCESS", result.get("PhysicalResourceId", "unknown"), result.get("Data", {})
        )
    except Exception as exc:  # noqa: BLE001 -- CFN must always be signaled, even on failure.
        _send_response(event, "FAILED", event.get("PhysicalResourceId", "unknown"), {}, reason=str(exc))


def _send_response(
    event: dict[str, Any],
    status: str,
    physical_id: str,
    data: dict[str, Any],
    *,
    reason: str = "",
) -> None:
    body = json.dumps(
        {
            "Status": status,
            "Reason": reason or "See CloudWatch logs",
            "PhysicalResourceId": physical_id,
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": data,
        }
    ).encode("utf-8")
    # CFN pre-signed HTTPS URL, not user input.
    request = urllib.request.Request(url=event["ResponseURL"], data=body, method="PUT")  # noqa: S310
    urllib.request.urlopen(request)  # noqa: S310
