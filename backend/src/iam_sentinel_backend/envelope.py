"""The success half of the response envelope every route uses (phase-00
§4's docstring already defines the shape; `errors.py` owns the failure
half). Centralized here so every phase-01 router builds the same
`{"ok": true, "data": ...}` wrapper instead of hand-rolling it per route.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def ok(data: BaseModel | dict[str, Any] | list[Any]) -> dict[str, Any]:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return {"ok": True, "data": payload}
