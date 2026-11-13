import asyncio
import contextvars
import subprocess
import sys
import threading

import pytest


def test_close_progresses_when_executor_result_precedes_its_queued_callback():
    script = """
import asyncio
from unittest.mock import patch
from stackchan_autonomy.async_storage import AsyncStorage
async def main():
    loop = asyncio.get_running_loop()
    storage = AsyncStorage()
    ready = loop.create_future()
    ready.set_result(7)
    # Model executor completion before the queued storage callback gets a loop turn.
    with patch.object(loop, 'run_in_executor', return_value=ready):
        assert await storage.call(lambda: 7) == 7
        await storage.aclose()
    print('cleanup-finished')
asyncio.run(main())
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=10
        )
    except subprocess.TimeoutExpired:
        pytest.fail("storage cleanup spun before its completion callback could run")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "cleanup-finished"


async def entered(event):
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.001)


async def test_storage_runs_off_loop_with_context_and_propagates_errors():
    from stackchan_autonomy.async_storage import AsyncStorage

    marker = contextvars.ContextVar("storage_test_context", default="absent")
    token = marker.set("caller-context")
    caller_thread = threading.get_ident()
    storage = AsyncStorage()

    def operation():
        value = marker.get()
        marker.set("worker-only")
        return value, threading.get_ident()

    def broken():
        raise ValueError("fixed test failure")

    try:
        value, worker_thread = await storage.call(operation)
        assert value == "caller-context" and worker_thread != caller_thread
        assert marker.get() == "caller-context"
        with pytest.raises(ValueError, match="fixed test failure"):
            await storage.call(broken)
        assert await storage.call(lambda: 7) == 7
    finally:
        marker.reset(token)
        await storage.aclose()


async def test_cancelled_waiters_do_not_submit_workers_behind_blocked_io(monkeypatch):
    from stackchan_autonomy.async_storage import AsyncStorage

    storage = AsyncStorage()
    started, release = threading.Event(), threading.Event()
    calls = []
    submitted = 0
    loop = asyncio.get_running_loop()
    original_submit = loop.run_in_executor

    def submit(*args, **kwargs):
        nonlocal submitted
        submitted += 1
        return original_submit(*args, **kwargs)

    def first():
        started.set()
        release.wait(3)
        calls.append(1)

    def second():
        calls.append(2)
        return 2

    monkeypatch.setattr(loop, "run_in_executor", submit)
    first_task = asyncio.create_task(storage.call(first))
    waiters = []
    try:
        await entered(started)
        first_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_task
        for _ in range(12):
            task = asyncio.create_task(storage.call(second))
            waiters.append(task)
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        final = asyncio.create_task(storage.call(second))
        waiters.append(final)
        await asyncio.sleep(0)
        assert submitted == 1, "canceled waiters occupied the shared executor"
        assert calls == []
        release.set()
        assert await final == 2
        assert calls == [1, 2] and submitted == 2
    finally:
        release.set()
        await asyncio.gather(first_task, *waiters, return_exceptions=True)
        await storage.aclose()


async def test_close_drains_abandoned_error_before_propagating_repeated_cancellation():
    from stackchan_autonomy.async_storage import AsyncStorage

    storage = AsyncStorage()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked():
        started.set()
        release.wait(3)
        finished.set()
        raise ValueError("abandoned worker error")

    operation = asyncio.create_task(storage.call(blocked))
    closer = None
    try:
        await entered(started)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        closer = asyncio.create_task(storage.aclose())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            await storage.call(lambda: None)
        closer.cancel()
        await asyncio.sleep(0)
        closer.cancel()
        await asyncio.sleep(0)
        assert not closer.done() and not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closer
        assert finished.is_set()
        await storage.aclose()
    finally:
        release.set()
        await asyncio.gather(operation, *([closer] if closer else []), return_exceptions=True)
        await storage.aclose()
