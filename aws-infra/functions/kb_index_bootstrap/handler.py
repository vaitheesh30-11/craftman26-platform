"""CloudFormation custom-resource Lambda that creates the vector index
`SentinelKB` needs on the `sentinel-kb-vector` OpenSearch Serverless
collection (aws-infra phase-05 §3). Mirrors `oss_index_bootstrap`
(aws-infra phase-02 / ADR 0005) -- same SigV4-over-`botocore` approach,
not `opensearchpy` -- but with its own index name/body: the field names
(`bedrock-knowledge-base-default-vector`, `AMAZON_BEDROCK_TEXT_CHUNK`,
`AMAZON_BEDROCK_METADATA`) are the exact names `CfnKnowledgeBase`'s
`OpenSearchServerlessFieldMappingProperty` wires into the KB's storage
configuration, so this index must exist before the KB's `CreateIngestionJob`
can run (Bedrock does not create the index itself for a customer-managed
OSS collection).
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

_SERVICE = "aoss"
_INDEX_NAME = "bedrock-knowledge-base-default-index"
_EMBEDDING_DIMENSIONS = 256
_INDEX_BODY = {
    "mappings": {
        "properties": {
            "bedrock-knowledge-base-default-vector": {
                "type": "knn_vector",
                "dimension": _EMBEDDING_DIMENSIONS,
                "method": {
                    "engine": "faiss",
                    "name": "hnsw",
                    "parameters": {"m": 16, "ef_construction": 100},
                },
            },
            "AMAZON_BEDROCK_TEXT_CHUNK": {"type": "text"},
            "AMAZON_BEDROCK_METADATA": {"type": "text", "index": False},
        }
    },
    "settings": {"index.knn": True},
}


def _signed_request(method: str, url: str, region: str, body: dict[str, Any] | None = None) -> Any:
    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("no AWS credentials available to sign the OpenSearch Serverless request")

    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = AWSRequest(method=method, url=url, data=data, headers={"Content-Type": "application/json"})
    SigV4Auth(credentials, _SERVICE, region).add_auth(request)
    prepared = request.prepare()

    urllib_request = urllib.request.Request(  # noqa: S310 -- AWS-signed collection endpoint, not user input.
        prepared.url, data=data, headers=dict(prepared.headers), method=method
    )
    with urllib.request.urlopen(urllib_request) as response:  # noqa: S310
        return json.loads(response.read())


def route_request(
    request_type: str,
    properties: dict[str, Any],
    physical_id: str | None,
) -> dict[str, Any]:
    """Pure dispatch, kept separate from `handler` for unit testing."""
    if request_type in ("Create", "Update"):
        endpoint = properties["CollectionEndpoint"].rstrip("/")
        # AOSS endpoints are {collection-id}.{region}.aoss.amazonaws.com.
        hostname = urlparse(endpoint).hostname
        if hostname is None:
            raise ValueError(f"CollectionEndpoint has no hostname: {endpoint!r}")
        region = hostname.split(".")[1]
        _signed_request("PUT", f"{endpoint}/{_INDEX_NAME}", region, _INDEX_BODY)
        return {"PhysicalResourceId": _INDEX_NAME}

    if request_type == "Delete":
        return {"PhysicalResourceId": physical_id or _INDEX_NAME}

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
