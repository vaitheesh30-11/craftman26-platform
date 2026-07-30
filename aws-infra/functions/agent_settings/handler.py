"""CloudFormation custom-resource Lambda that sets the two Bedrock Agent
fields `aws_cdk.aws_bedrock.CfnAgent` cannot express on aws-cdk-lib 2.163.0:
`agentCollaboration` (multi-agent SUPERVISOR/DISABLED) and
`memoryConfiguration` (SESSION_SUMMARY retention). Confirmed via
`boto3==1.35.36`'s own service model that both fields exist on the real
`UpdateAgent`/`CreateAgent` APIs -- the CDK L1 construct simply predates
them (phase-05 §10 already calls this out as a live risk: "Multi-agent
collaboration API surface changes; still evolving"). `UpdateAgent` requires
resending `agentName`/`foundationModel`/`instruction`/`agentResourceRoleArn`
verbatim -- it is a full-replace API, not a patch -- so this custom
resource's properties mirror `SentinelBedrockAgent`'s own CfnAgent call
exactly, and `SentinelBedrockAgent` is the only caller.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import boto3

_bedrock_agent = boto3.client("bedrock-agent")


def route_request(
    request_type: str,
    properties: dict[str, Any],
    physical_id: str | None,
) -> dict[str, Any]:
    """Pure dispatch, kept separate from `handler` for unit testing."""
    if request_type in ("Create", "Update"):
        agent_id = properties["AgentId"]
        kwargs: dict[str, Any] = {
            "agentId": agent_id,
            "agentName": properties["AgentName"],
            "agentResourceRoleArn": properties["AgentResourceRoleArn"],
            "foundationModel": properties["FoundationModel"],
            "instruction": properties["Instruction"],
        }
        if properties.get("AgentCollaboration") is not None:
            kwargs["agentCollaboration"] = properties["AgentCollaboration"]
        if properties.get("MemoryConfiguration") is not None:
            kwargs["memoryConfiguration"] = properties["MemoryConfiguration"]

        _bedrock_agent.update_agent(**kwargs)
        return {"PhysicalResourceId": agent_id}

    if request_type == "Delete":
        # The agent itself is owned and deleted by `CfnAgent`; this
        # resource only ever mutates fields on an agent that already
        # exists, so there is nothing of its own to tear down.
        return {"PhysicalResourceId": physical_id or "already-deleted"}

    raise ValueError(f"unsupported RequestType: {request_type!r}")


def handler(event: dict[str, Any], _context: object) -> None:
    try:
        result = route_request(
            event["RequestType"], event.get("ResourceProperties", {}), event.get("PhysicalResourceId")
        )
        _send_response(event, "SUCCESS", result.get("PhysicalResourceId", "unknown"), {})
    except Exception as exc:  # noqa: BLE001 -- CFN must always be signaled, even on failure.
        _send_response(event, "FAILED", event.get("PhysicalResourceId", "unknown"), {}, reason=str(exc))


def _send_response(
    event: dict[str, Any], status: str, physical_id: str, data: dict[str, Any], *, reason: str = ""
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
    request = urllib.request.Request(url=event["ResponseURL"], data=body, method="PUT")  # noqa: S310
    urllib.request.urlopen(request)  # noqa: S310
