from __future__ import annotations

import pytest

from iam_sentinel_backend.auth.breakglass import (
    BreakGlassVerificationError,
    verify_breakglass_header,
)


def test_verify_breakglass_header_accepts_the_two_signer_tag() -> None:
    assert verify_breakglass_header("BreakGlass=IAMSentinel-Two-Signer") is True


def test_verify_breakglass_header_rejects_missing_header() -> None:
    with pytest.raises(BreakGlassVerificationError):
        verify_breakglass_header(None)


def test_verify_breakglass_header_rejects_mismatched_value() -> None:
    with pytest.raises(BreakGlassVerificationError):
        verify_breakglass_header("BreakGlass=SomethingElse")
