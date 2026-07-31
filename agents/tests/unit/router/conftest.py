"""`test_fast_path.py`'s F1/F7 fixtures attach real AWS managed policies --
moto only loads its bundled copies of those policies when this env var is
set (moto/settings.py: `load_iam_aws_managed_policies`). Set at collection
time, before any `@mock_aws`-decorated test creates an IAM backend, same
precedent as `tests/unit/f1/conftest.py`.
"""

from __future__ import annotations

import os

os.environ.setdefault("MOTO_IAM_LOAD_MANAGED_POLICIES", "true")
