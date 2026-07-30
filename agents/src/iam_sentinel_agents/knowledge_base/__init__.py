"""RAG knowledge-base grounding: quote-manifest generation/verification and
the freshness contract on top of `SentinelKB` retrieval (agents phase-10).

Scope note: this package builds the pieces `agents/` owns directly --
manifest construction (pure Python), the production `QuoteManifest`
provider, the freshness check, and the retrieval wrapper around
`LLMProvider.retrieve()` (already built in adapters phase-01). The
`SentinelKBStack` CDK stack, the corpus-fetch/ingestion Lambdas, and the
Bedrock Knowledge Base itself are deferred -- see docs/decisions/0010.
"""

from __future__ import annotations
