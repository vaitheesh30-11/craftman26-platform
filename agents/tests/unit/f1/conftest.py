"""F1's fixtures attach real AWS managed policies (`AdministratorAccess`,
`PowerUserAccess`) to prove the privilege-classification rubric against the
same policy names a real account would have -- moto only loads its bundled
copies of those policies when this env var is set (moto/settings.py:
`load_iam_aws_managed_policies`). Set at collection time, before any
`@mock_aws`-decorated test creates an IAM backend.
"""

from __future__ import annotations

import os

os.environ.setdefault("MOTO_IAM_LOAD_MANAGED_POLICIES", "true")
