"""`kms:Sign` wrapper for evidence signatures (phase-04 §6)."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Literal

import boto3

from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_kms import KMSClient

_SIGNING_ALGORITHM: Literal["RSASSA_PSS_SHA_256"] = "RSASSA_PSS_SHA_256"
_MESSAGE_TYPE: Literal["DIGEST"] = "DIGEST"


class KmsSigner:
    def __init__(self, *, key_arn: str, client: KMSClient | None = None) -> None:
        self._key_arn = key_arn
        self._kms: KMSClient = client or boto3.client("kms", region_name=settings.region)

    def sign_digest(self, digest: bytes) -> str:
        response = self._kms.sign(
            KeyId=self._key_arn,
            Message=digest,
            MessageType=_MESSAGE_TYPE,
            SigningAlgorithm=_SIGNING_ALGORITHM,
        )
        return base64.b64encode(response["Signature"]).decode("ascii")
