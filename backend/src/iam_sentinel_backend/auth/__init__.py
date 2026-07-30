"""Auth surface: Cognito JWT verifier, SigV4 verifier, break-glass tag check.

`Principal` is the shared output shape every verifier returns (phase-00 §2
`Depends(get_principal)`).
"""

from __future__ import annotations

from iam_sentinel_backend.auth.principal import AuthKind, Principal

__all__ = ["AuthKind", "Principal"]
