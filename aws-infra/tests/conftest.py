"""`functions/*` modules construct a boto3 client at import time (safe in a
real Lambda, where AWS_REGION is always set) — set a default region before
pytest imports anything under `functions/` so local collection doesn't
require real AWS credentials.
"""

from __future__ import annotations

import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
