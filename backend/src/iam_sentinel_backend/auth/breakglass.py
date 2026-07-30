"""Break-glass session-tag check (phase-00 §3, `/emergency/*` gate).

`/emergency/kill-session` additionally requires the caller's session to
carry `BreakGlass=IAMSentinel-Two-Signer` (aws-infra phase-01's two-signer
STS workflow is the only thing that ever issues that tag, per
`docs/decisions/0001` and SYSTEM_STATE.md §2 rule 10). Verification here is
header-based: API Gateway's IAM authorizer reflects the caller's assumed-
role session tags into the request context for `/emergency/*` (a Lambda
authorizer per `aws-infra/docs/phase-07-api-stack.txt §6`); this module
trusts that reflected value the same way `from_apigw_identity` trusts
`userArn` -- both are upstream-verified, never re-derived here.
"""

from __future__ import annotations

from iam_sentinel_backend.settings import settings


class BreakGlassVerificationError(Exception):
    """Raised when a caller lacks (or presents a mismatched) break-glass tag."""


def verify_breakglass_header(header_value: str | None) -> bool:
    """Return True iff `header_value` carries the exact two-signer tag.

    Callers of this function are routes gated behind `/emergency/*` --
    absence or mismatch MUST raise, never silently degrade to "not
    break-glass" (SYSTEM_STATE.md rule 6: conservative-default failure).
    """
    expected = f"{settings.breakglass_session_tag_key}={settings.breakglass_session_tag_value}"
    if header_value is None:
        raise BreakGlassVerificationError(
            f"missing required header {settings.breakglass_header_name!r}"
        )
    if header_value != expected:
        raise BreakGlassVerificationError(
            "break-glass session tag does not match the two-signer tag"
        )
    return True
