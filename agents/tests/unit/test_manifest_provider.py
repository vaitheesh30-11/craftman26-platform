"""KbManifestProvider verifies via KMS on cache-miss and caches the result
for kb_manifest_refresh_seconds (agents phase-10 §Acceptance)."""

from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_agents.knowledge_base.manifest_provider import KbManifestProvider

_KNOWN_HASH = "b" * 64


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.get_verified.return_value = {
        "manifest_version": "1",
        "generated_at": "2026-07-30T00:00:00Z",
        "total_quotes": 1,
        "quotes": [
            {
                "quote_sha256": _KNOWN_HASH,
                "corpus": "iam",
                "document": "passrole.md",
                "span_start": 0,
                "span_end": 10,
                "retrieved_on": "2026-07-30",
            }
        ],
        "manifest_sha256": "c" * 64,
        "signature": "c2lnbmF0dXJl",
        "kms_key_arn": "arn:aws:kms:us-east-1:111111111111:key/kb-manifest",
    }
    return client


def test_provider_contains_known_hash_and_rejects_unknown() -> None:
    client = _fake_client()
    provider = KbManifestProvider(client=client)

    manifest = provider()

    assert manifest is not None
    assert manifest.contains(_KNOWN_HASH) is True
    assert manifest.contains("f" * 64) is False


def test_provider_caches_and_does_not_refetch_within_ttl() -> None:
    client = _fake_client()
    provider = KbManifestProvider(client=client)

    provider()
    provider()

    client.get_verified.assert_called_once()
