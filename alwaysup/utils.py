from typing import Awaitable, Any
import mflog
import asyncio
from functools import wraps


async def log_exceptions(awaitable: Awaitable[Any]):
    """Wrap a coroutine to catch and log exceptions raised."""
    try:
        return await awaitable
    except asyncio.CancelledError:
        pass
    except Exception:
        mflog.exception("Unhandled exception")


class AsyncMutuallyExclusive:
    """Decorator for coroutines to manage a mutually exclusive lock on the instance.

    Attributes:
        wait: If True, we will wait for the lock. If False, the call will be silently
            ignored (if we don't get the lock of course).
    """

    def __init__(self, wait: bool = True):
        self.wait: bool = wait

    def __call__(self, f):
        @wraps(f)
        async def wrapper(obj, *args, **kwargs):
            try:
                lock = getattr(obj, "__aiomutuallyexclusivelock")
            except AttributeError:
                lock = asyncio.Lock()
                setattr(obj, "__aiomutuallyexclusivelock", lock)
            if not self.wait and lock.locked():
                return
            async with lock:
                return await f(obj, *args, **kwargs)

        return wrapper
