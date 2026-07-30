"""Export the current OpenAPI schema to `backend/openapi.golden.json`
(phase-00 §4 Step 6, §5 Test Plan "Contract: OpenAPI schema round-trip").

Run manually after adding/changing a route:

    uv run python scripts/export_openapi.py

CI (`backend-ci.yml`) re-runs this into a temp file and diffs it against the
committed golden file -- a PR that changes the API surface without
regenerating the golden file fails the `contract` job.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iam_sentinel_backend.app import create_app


def main() -> None:
    schema = create_app().openapi()
    out_path = Path(__file__).resolve().parent.parent / "openapi.golden.json"
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
