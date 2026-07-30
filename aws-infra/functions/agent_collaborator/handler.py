"""CloudFormation custom-resource Lambda wrapping
`bedrock-agent:AssociateAgentCollaborator` / `UpdateAgentCollaborator` /
`DisassociateAgentCollaborator` (phase-05 §6). CloudFormation has no native
`AWS::Bedrock::AgentCollaborator` resource, matching the same gap the
Guardrail lifecycle Lambda (aws-infra phase-01) closes for
`AWS::Bedrock::Guardrail`.

Every association targets the Supervisor's DRAFT version -- a collaborator
must be associated before `PrepareAgent` promotes a new version, and this
phase's aliases are all created against DRAFT (phase-05 §4/§7) -- so
`agentVersion` is always the literal `"DRAFT"`, never a caller-supplied
property.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import boto3

_bedrock_agent = boto3.client("bedrock-agent")
_DRAFT = "DRAFT"


def route_request(
    request_type: str,
    properties: dict[str, Any],
    physical_id: str | None,
) -> dict[str, Any]:
    """Pure dispatch, kept separate from `handler` for unit testing."""
    supervisor_agent_id = properties["SupervisorAgentId"]

    if request_type == "Create":
        created = _bedrock_agent.associate_agent_collaborator(
            agentId=supervisor_agent_id,
            agentVersion=_DRAFT,
            collaboratorName=properties["CollaboratorName"],
            collaborationInstruction=properties["CollaborationInstruction"],
            agentDescriptor={"aliasArn": properties["CollaboratorAliasArn"]},
            relayConversationHistory=properties.get("RelayConversationHistory", "TO_COLLABORATOR"),
        )
        collaborator_id = created["agentCollaborator"]["collaboratorId"]
        return {"PhysicalResourceId": collaborator_id}

    if request_type == "Update":
        if physical_id is None:
            raise ValueError("Update requested without a physical resource id")
        _bedrock_agent.update_agent_collaborator(
            agentId=supervisor_agent_id,
            agentVersion=_DRAFT,
            collaboratorId=physical_id,
            collaboratorName=properties["CollaboratorName"],
            collaborationInstruction=properties["CollaborationInstruction"],
            agentDescriptor={"aliasArn": properties["CollaboratorAliasArn"]},
            relayConversationHistory=properties.get("RelayConversationHistory", "TO_COLLABORATOR"),
        )
        return {"PhysicalResourceId": physical_id}

    if request_type == "Delete":
        if physical_id is not None:
            _bedrock_agent.disassociate_agent_collaborator(
                agentId=supervisor_agent_id, agentVersion=_DRAFT, collaboratorId=physical_id
            )
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
