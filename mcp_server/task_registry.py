"""
Shared background task registry.

Solves RUF006: asyncio.create_task returns a weakly-referenced task. If
the caller doesn't keep a reference, garbage collection can reap the
task mid-run, causing background loops to die silently.

Every long-lived background loop should be registered via `track()` so:
  1. The task set holds a strong reference until the task completes.
  2. A done-callback removes the task from the set on completion.
  3. A done-callback logs at ERROR if the task ended with an exception —
     so a dying loop is visible in production instead of silently gone.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Strong references to all live background tasks. `set` (not list) so the
# discard callback is O(1). Callers should not mutate this set directly.
_background_tasks: set[asyncio.Task] = set()


def _on_task_done(task: asyncio.Task) -> None:
    """Discard from registry; surface any unhandled exception at ERROR."""
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Background task %r ended with exception: %s",
            task.get_name(), exc, exc_info=exc,
        )


def track(task: asyncio.Task, *, name: str | None = None) -> asyncio.Task:
    """Register a background task so it survives GC and reports failures.

    Usage:
        track(asyncio.create_task(my_loop(), name="my-loop"))

    The `name` kwarg is a convenience — if given, it sets task.set_name(name)
    before registering, so the ERROR log line identifies the loop.
    """
    if name is not None:
        try:
            task.set_name(name)
        except Exception:
            pass
    _background_tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


def active_count() -> int:
    """Number of live tracked tasks — for diagnostics/health endpoints."""
    return len(_background_tasks)
