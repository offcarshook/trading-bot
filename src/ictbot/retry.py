"""Retry with exponential backoff for transient API / network failures.

alpaca-py already retries HTTP 429/504 internally (3 attempts, 3s apart in
0.44.0). This wrapper adds backoff for connection errors and 5xx responses.
4xx errors (bad request, insufficient qty, duplicate client_order_id ...) are
NOT retried: they are deterministic and retrying could only make things worse.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from typing import Callable, TypeVar

import requests

T = TypeVar("T")
log = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 4
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 20.0


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout, ConnectionError, TimeoutError)):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    return False


def call_with_retry(
    fn: Callable[[], T],
    *,
    what: str,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified below
            if attempt >= attempts or not is_transient(exc):
                raise
            delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * (0.8 + 0.4 * random.random())
            log.warning("transient error, retrying", extra={"what": what, "attempt": attempt, "delay_s": round(delay, 2), "error": str(exc)[:300]})
            sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def retrying(what: str, attempts: int = DEFAULT_ATTEMPTS) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            return call_with_retry(lambda: fn(*args, **kwargs), what=what, attempts=attempts)

        return wrapper

    return deco
