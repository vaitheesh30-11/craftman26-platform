"""Lambda entrypoint for `SentinelApi`'s proxy integration.

Per ADR 0017, this module is a thin shim over `iam_sentinel_backend.app`,
not a reimplementation -- `backend` phase-00 already built the real
`create_app()`/`Mangum` handler (`backend/src/iam_sentinel_backend/app.py`).
What this phase cannot yet do is *package* `backend`'s dependency closure
(fastapi, mangum, pydantic, pyjwt-free but still `requests`, plus
`iam_sentinel_adapters`) into this Lambda's deployment asset: the same
pip-bundling gap ADR 0011 and ADR 0015 already flagged for
`functions/layers/{boto3,powertools}/python/` (still empty `.gitkeep`
placeholders) blocks a `from_asset` zip of `functions/backend_api/` alone
from having any of those packages on `sys.path` at runtime.

Until that packaging pipeline exists (e.g. `aws_cdk.aws_lambda_python_alpha
.PythonFunction` with Docker bundling, or a CI-built layer following
phase-04 §6's own layer-build precedent), invoking this Lambda for real
returns a deterministic 502 rather than an `ImportError` traceback leaking
to a caller -- `handler()` degrades explicitly instead of failing open or
silently. Swap this shim out (or delete it) once `iam_sentinel_backend` is
actually importable from this Lambda's runtime.
"""

from __future__ import annotations

import json
from typing import Any

try:
    # `iam_sentinel_backend` is never installed in this Lambda's runtime
    # yet (see the module docstring) -- mypy checks aws-infra and backend
    # as two independent packages, so this import is expected-missing
    # here, not a real type error.
    from iam_sentinel_backend.app import (
        handler as _mangum_handler,  # type: ignore[import-not-found]
    )
except ImportError:
    _mangum_handler = None


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    if _mangum_handler is None:
        return {
            "statusCode": 502,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "BACKEND_NOT_PACKAGED",
                        "message": (
                            "iam_sentinel_backend is not bundled into this Lambda's "
                            "deployment package yet -- see functions/backend_api/handler.py "
                            "and ADR 0017."
                        ),
                    },
                }
            ),
        }
    result: dict[str, Any] = _mangum_handler(event, context)
    return result
