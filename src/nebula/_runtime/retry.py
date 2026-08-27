from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 2
    base_seconds: float = 0.25
    max_seconds: float = 8.0


DEFAULT_RETRY = RetryPolicy()

# 421 reports that this request reached a region that does not own the
# collection. Ownership is durable and the routing directory converges, so
# the misroute is transient; the edge replays what it can, and retrying
# covers the requests it cannot (uncloneable bodies, unannotated routes).
_RETRYABLE_STATUSES: frozenset[int] = frozenset({421, 429, 503})


def is_retryable_status(status: int) -> bool:
    return status in _RETRYABLE_STATUSES


def backoff_seconds(
    attempt: int, policy: RetryPolicy, retry_after: Optional[float] = None
) -> float:
    cap = min(policy.base_seconds * (2 ** attempt), policy.max_seconds)
    jitter = random.uniform(0, cap)
    if retry_after is not None:
        # Retry-After is a server-imposed minimum, not ordinary client backoff.
        return max(jitter, max(0.0, retry_after))
    return jitter
