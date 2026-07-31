"""Production `QuoteManifest` provider for `Finding.aws_doc_citation`
(agents phase-10 §Acceptance: "Manifest KMS signature verifies on every
read"). Installed once at Lambda cold start via
`install_production_manifest_provider`; tests instead use
`agents/tests/conftest.py`'s in-memory fixture.

Caches the verified manifest in-process for
`settings.kb_manifest_refresh_seconds` (default 1 hour, phase-00's
placeholder) so a warm container doesn't re-fetch and re-verify against
KMS on every single `Finding` construction -- only every cache-miss re-does
the full get+verify round trip.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from iam_sentinel_adapters.knowledge_base.manifest_client import KbManifestClient

from iam_sentinel_agents.contracts.finding import set_quote_manifest_provider
from iam_sentinel_agents.contracts.knowledge_base import KbManifest
from iam_sentinel_agents.settings import settings

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.finding import QuoteManifest


class _CachedManifest:
    def __init__(self, quote_hashes: frozenset[str]) -> None:
        self._hashes = quote_hashes

    def contains(self, quote_sha256: str) -> bool:
        return quote_sha256 in self._hashes


class KbManifestProvider:
    def __init__(self, *, client: KbManifestClient | None = None) -> None:
        self._client = client or KbManifestClient()
        self._cached: _CachedManifest | None = None
        self._loaded_at: float = 0.0

    def __call__(self) -> QuoteManifest | None:
        now = time.monotonic()
        if (
            self._cached is not None
            and now - self._loaded_at < settings.kb_manifest_refresh_seconds
        ):
            return self._cached

        parsed = self._client.get_verified()
        manifest = KbManifest.model_validate(parsed)
        self._cached = _CachedManifest(frozenset(q.quote_sha256 for q in manifest.quotes))
        self._loaded_at = now
        return self._cached


def install_production_manifest_provider(
    *, client: KbManifestClient | None = None
) -> KbManifestProvider:
    provider = KbManifestProvider(client=client)
    set_quote_manifest_provider(provider)
    return provider
