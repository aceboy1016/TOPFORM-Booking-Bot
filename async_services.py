"""Bound blocking Google clients without blocking the ASGI event loop."""
import asyncio

# The shared googleapiclient/httplib2 transport is not thread-safe.
_google_slots = asyncio.Semaphore(1)

async def google_call(function, *args, **kwargs):
    async with _google_slots:
        return await asyncio.to_thread(function, *args, **kwargs)
