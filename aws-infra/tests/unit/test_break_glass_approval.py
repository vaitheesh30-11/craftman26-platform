from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from approval import evaluate_two_signer

_T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)


def test_two_distinct_signers_within_window_approves() -> None:
    approved = evaluate_two_signer(
        first_principal_id="AROA1111:alice",
        first_signed_at=_T0,
        second_principal_id="AROA2222:bob",
        second_signed_at=_T0 + timedelta(seconds=30),
    )
    assert approved is True


def test_same_principal_signing_twice_is_denied() -> None:
    approved = evaluate_two_signer(
        first_principal_id="AROA1111:alice",
        first_signed_at=_T0,
        second_principal_id="AROA1111:alice",
        second_signed_at=_T0 + timedelta(seconds=10),
    )
    assert approved is False


def test_distinct_signers_outside_window_is_denied() -> None:
    approved = evaluate_two_signer(
        first_principal_id="AROA1111:alice",
        first_signed_at=_T0,
        second_principal_id="AROA2222:bob",
        second_signed_at=_T0 + timedelta(seconds=61),
    )
    assert approved is False


def test_boundary_at_exactly_sixty_seconds_approves() -> None:
    approved = evaluate_two_signer(
        first_principal_id="AROA1111:alice",
        first_signed_at=_T0,
        second_principal_id="AROA2222:bob",
        second_signed_at=_T0 + timedelta(seconds=60),
    )
    assert approved is True


@pytest.mark.parametrize("delta_seconds", [-30, -61])
def test_second_signer_before_first_is_evaluated_by_absolute_distance(delta_seconds: int) -> None:
    approved = evaluate_two_signer(
        first_principal_id="AROA1111:alice",
        first_signed_at=_T0,
        second_principal_id="AROA2222:bob",
        second_signed_at=_T0 + timedelta(seconds=delta_seconds),
    )
    assert approved is (delta_seconds == -30)
