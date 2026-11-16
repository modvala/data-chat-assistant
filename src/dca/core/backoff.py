"""Backoff for retries of external calls (V8, HLD 15.2): full jitter, `Retry-After` when given."""

import random

from dca.config import Retry


def delay(attempt: int, retry_after: float | None, retry: Retry, rng: random.Random | None = None) -> float:
    """The wait before retry number `attempt` (1, 2, ...), from `backoff_min_s` to `backoff_max_s`."""
    if retry_after is not None:
        return min(max(retry_after, retry.backoff_min_s), retry.backoff_max_s)
    cap = min(retry.backoff_max_s, retry.backoff_min_s * 2**attempt)
    return (rng or random).uniform(retry.backoff_min_s, cap)
