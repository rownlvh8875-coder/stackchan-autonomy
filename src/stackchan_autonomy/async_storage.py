"""Tracked serial file IO without blocking the loop or abandoning atomic writes."""

import asyncio
import contextvars
from functools import partial


async def finish_cleanup(future: asyncio.Future):
    """Finish resource cleanup before propagating even repeated caller cancellation."""
    cancelled = False
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            if future.cancelled():
                raise
            cancelled = True
    result = future.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class AsyncStorage:
    def __init__(self):
        self._slot = asyncio.Lock()
        self._pending: set[asyncio.Future] = set()
        self._closed = False

    @property
    def pending(self) -> bool:
        return bool(self._pending)

    def _finished(self, future):
        if future not in self._pending:
            return
        self._pending.remove(future)
        self._slot.release()
        if not future.cancelled():
            future.exception()  # Retrieve errors even if the awaiting caller was canceled.

    async def call(self, operation, *args, **kwargs):
        if self._closed:
            raise RuntimeError("storage worker closed")
        # Admission happens before submission. The worker's completion owns this slot,
        # so caller cancellation cannot submit competing IO or exhaust the shared pool.
        await self._slot.acquire()
        if self._closed:
            self._slot.release()
            raise RuntimeError("storage worker closed")
        try:
            context = contextvars.copy_context()
            future = asyncio.get_running_loop().run_in_executor(
                None, context.run, partial(operation, *args, **kwargs)
            )
        except BaseException:
            self._slot.release()
            raise
        self._pending.add(future)
        future.add_done_callback(self._finished)
        return await asyncio.shield(future)

    async def drain(self):
        while self._pending:
            # A Future can be done while its queued callback has not had a loop turn.
            # gather(done_future) may complete eagerly, so finish it idempotently here.
            for future in tuple(self._pending):
                if future.done():
                    self._finished(future)
            if self._pending:
                await finish_cleanup(asyncio.gather(*tuple(self._pending), return_exceptions=True))

    async def aclose(self):
        self._closed = True
        await self.drain()
