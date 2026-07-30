"""Contract test (phase-00 §5): the live OpenAPI schema must match the
committed golden file exactly. A route added without running
`scripts/export_openapi.py` fails here -- same enforcement `backend-ci.yml`
runs as its `contract` job.
"""

from __future__ import annotations

import json
from pathlib import Path

from iam_sentinel_backend.app import create_app

_GOLDEN_PATH = Path(__file__).resolve().parent.parent.parent / "openapi.golden.json"


def test_openapi_schema_matches_the_committed_golden_file() -> None:
    live_schema = create_app().openapi()
    golden_schema = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))

    assert live_schema == golden_schema, (
        "OpenAPI schema drifted from openapi.golden.json -- "
        "run `uv run python scripts/export_openapi.py` and commit the result."
    )
