"""Shared pytest fixtures for the backend module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from iam_sentinel_backend.settings import settings

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _restore_settings() -> Iterator[None]:
    """`settings` is a process-lifetime singleton (phase-00 §7 convention);
    tests that mutate it directly (rather than constructing their own
    `BackendSettings()`) must not leak state across test cases.
    """
    snapshot = settings.model_dump()
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)
