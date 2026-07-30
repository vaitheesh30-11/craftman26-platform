"""Manifest generation orchestration -- the `kb_manifest_generate` Lambda's
core logic (agents phase-10 §2, §4 step 2). The CDK stack and Lambda
handler wrapper that would invoke this on a schedule are deferred (no
CDK stack exists for this phase; see docs/decisions/0010) -- this function
is code-complete and directly callable once that wrapper lands.
"""

from __future__ import annotations

from datetime import datetime, UTC

from iam_sentinel_adapters.knowledge_base.manifest_client import KbManifestClient

from iam_sentinel_agents.contracts.knowledge_base import KbManifest, QuoteHash
from iam_sentinel_agents.knowledge_base.manifest_builder import canonical_manifest_digest

_MANIFEST_VERSION = "1"


def build_and_publish_manifest(
    quotes: list[QuoteHash], *, client: KbManifestClient | None = None
) -> KbManifest:
    sorted_quotes = sorted(quotes, key=lambda q: (q.corpus, q.document, q.span_start))
    manifest_sha256_hex, digest = canonical_manifest_digest(sorted_quotes)

    resolved_client = client or KbManifestClient()
    signature = resolved_client.sign(digest)
    generated_at = datetime.now(UTC)

    manifest = KbManifest(
        manifest_version=_MANIFEST_VERSION,
        generated_at=generated_at,
        total_quotes=len(sorted_quotes),
        quotes=sorted_quotes,
        manifest_sha256=manifest_sha256_hex,
        signature=signature,
        kms_key_arn=resolved_client.kms_key_arn,
    )

    version_key = f"manifest/{manifest.manifest_version}-{generated_at.date().isoformat()}.json"
    resolved_client.put(body=manifest.model_dump(mode="json"), version_key=version_key)
    return manifest
