"""KMS-signed evidence primitives. Only `canonicalize.py` exists so far,
pulled forward from adapters phase-04 because the prompts adapter
(phase-03) needs a deterministic JSON representation of `trusted_input`
before it lands here in full.
"""

from __future__ import annotations
