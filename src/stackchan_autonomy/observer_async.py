"""One tracked serial worker; cancellation drains IO before closing its link."""

import asyncio

from .async_storage import AsyncStorage, finish_cleanup
from .observer import DEFAULT_PROFILE, ObserverClient


class AsyncObserver:
    def __init__(self, port, profile=DEFAULT_PROFILE, *, client=None):
        self.client = client if client is not None else ObserverClient(port, profile)
        self.worker = AsyncStorage()

    async def __aenter__(self):
        try:
            await self.worker.call(self.client.__enter__)
            return self
        except BaseException:
            await self.aclose()
            raise

    async def __aexit__(self, *exc):
        await self.aclose()

    async def capture(self):
        return await self.worker.call(self.client.capture)

    async def aclose(self):
        async def close():
            try:
                await self.worker.call(self.client.close)
            finally:
                await self.worker.aclose()

        await finish_cleanup(asyncio.create_task(close()))
