"""build_and_publish_manifest signs via KMS and publishes both the current
and versioned manifest keys (agents phase-10 §4 step 2)."""

from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_agents.contracts.knowledge_base import QuoteHash
from iam_sentinel_agents.knowledge_base.manifest_service import build_and_publish_manifest

_QUOTE = QuoteHash(
    quote_sha256="a" * 64,
    corpus="iam",
    document="passrole.md",
    span_start=0,
    span_end=10,
    retrieved_on="2026-07-30",
)


def test_build_and_publish_manifest_signs_and_publishes() -> None:
    fake_client = MagicMock()
    fake_client.sign.return_value = "c2lnbmF0dXJl"
    fake_client.kms_key_arn = "arn:aws:kms:us-east-1:111111111111:key/kb-manifest"

    manifest = build_and_publish_manifest([_QUOTE], client=fake_client)

    assert manifest.total_quotes == 1
    assert manifest.signature == "c2lnbmF0dXJl"
    assert manifest.kms_key_arn == fake_client.kms_key_arn
    fake_client.sign.assert_called_once()
    fake_client.put.assert_called_once()
    put_kwargs = fake_client.put.call_args.kwargs
    assert put_kwargs["body"]["manifest_sha256"] == manifest.manifest_sha256
    assert put_kwargs["version_key"].startswith("manifest/1-")
