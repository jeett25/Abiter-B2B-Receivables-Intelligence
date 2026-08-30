from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")

MAX_TOOL_ATTEMPTS = 2  # one retry, then the caller decides the fallback


def call_with_retry(
    fn: Callable[[], T],
    is_success: Callable[[T], bool],
    max_attempts: int = MAX_TOOL_ATTEMPTS,
) -> tuple[T, int]:
    """Returns (last_result, attempts_made). Never raises on fn's behalf --
    if fn itself can raise, that's the caller's concern (every
    app.agent.tools function already guarantees it never does)."""
    result: T | None = None
    for attempt in range(1, max_attempts + 1):
        result = fn()
        if is_success(result):
            return result, attempt
    return result, max_attempts
