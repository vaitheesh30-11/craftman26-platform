"""Request/response Pydantic models for backend phase-01's REST endpoints.

These mirror `docs/DATA_CONTRACTS.md`'s wire shapes but are backend-local
definitions, not imports of `agents.contracts` -- `backend/README.md §1`'s
module boundary ("never imports from `agents/tools/`... speaks to
specialists only via Prime or the router-bridge") and the precedent already
set by `auth/principal.py`'s docstring ("Backend-local model -- not part of
`docs/DATA_CONTRACTS.md`") both point the same way: `backend`'s
`pyproject.toml` depends only on `iam-sentinel-adapters`, never
`iam-sentinel-agents`. Mirroring keeps that dependency edge from existing at
all, at the cost of manually keeping these in sync with the canonical
contracts -- the same trade-off `adapters`' table clients already made by
passing plain dicts instead of importing `agents.contracts.Finding`.
"""

from __future__ import annotations
