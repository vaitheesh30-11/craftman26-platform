"""The `Principal` shape every auth path resolves to (phase-00 §2/§3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

AuthKind = Literal["cognito", "sigv4"]


class Principal(BaseModel):
    """Backend-local model -- not part of `docs/DATA_CONTRACTS.md` (that
    file only covers producer/consumer wire contracts between modules).
    `arn` is either a real IAM ARN (SigV4 path) or a synthetic Cognito ARN
    (`arn:aws:cognito-idp:<region>:<account>:userpool/<pool-id>/<sub>`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arn: str
    groups: tuple[str, ...] = ()
    auth_kind: AuthKind
    email: str | None = None
    breakglass_verified: bool = False

    def is_in_group(self, group: str) -> bool:
        return group in self.groups
