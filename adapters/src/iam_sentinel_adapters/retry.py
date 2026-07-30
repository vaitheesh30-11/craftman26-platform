"""Retry decorator wrapping `tenacity` with per-policy backoff and a hard cap.

Every policy enforces a total-time ceiling via `stop_after_delay` so a
misbehaving dependency can never hold a Lambda invocation hostage (phase-00
§4). `NonRetryableError` subclasses are never retried because `retry_on`
only matches `TransientError` by default — callers must not widen it.
"""

from __future__ import annotations

from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from tenacity import (
    retry as _tenacity_retry,
)
from tenacity import (
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_random_exponential,
)

from iam_sentinel_adapters.errors import TransientError

if TYPE_CHECKING:
    from collections.abc import Callable

    from tenacity.stop import stop_base

P = ParamSpec("P")
T = TypeVar("T")


class Policy(Enum):
    """(label, max_retries, initial_wait, exp_base, max_wait, jitter)."""

    AGGRESSIVE = ("aggressive", 5, 0.2, 2.0, 5.0, 0.25)
    CAUTIOUS = ("cautious", 3, 0.5, 3.0, 10.0, 0.20)
    SINGLE = ("single", 1, 0.2, 1.0, 0.2, 0.0)
    NONE = ("none", 0, 0.0, 1.0, 0.0, 0.0)

    def __init__(
        self,
        label: str,
        max_retries: int,
        initial_wait: float,
        exp_base: float,
        max_wait: float,
        jitter: float,
    ) -> None:
        self.label = label
        self.max_retries = max_retries
        self.initial_wait = initial_wait
        self.exp_base = exp_base
        self.max_wait = max_wait
        self.jitter = jitter

    @property
    def total_time_cap(self) -> float:
        """Worst case: every retry waits `max_wait` plus its jitter margin."""
        return self.max_retries * self.max_wait * (1.0 + self.jitter)


def retry(
    *,
    policy: Policy,
    retry_on: tuple[type[Exception], ...] = (TransientError,),
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    stop: stop_base
    if policy.max_retries == 0:
        stop = stop_after_attempt(1)
    else:
        stop = stop_after_attempt(policy.max_retries + 1) | stop_after_delay(policy.total_time_cap)

    tenacity_decorator = _tenacity_retry(
        stop=stop,
        wait=wait_random_exponential(
            multiplier=policy.initial_wait,
            exp_base=policy.exp_base,
            max=policy.max_wait,
        ),
        retry=retry_if_exception_type(retry_on),
        reraise=True,
    )

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        wrapped = tenacity_decorator(fn)

        @wraps(fn)
        def inner(*args: P.args, **kwargs: P.kwargs) -> T:
            return wrapped(*args, **kwargs)

        return inner

    return decorator
