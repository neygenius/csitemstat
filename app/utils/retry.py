import asyncio
import logging
from typing import Callable, TypeVar, Awaitable

T = TypeVar("T")
logger = logging.getLogger(__name__)

async def retry_async(
    func: Callable[[], Awaitable[T]],
    retries: int = 5,
    delay: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> T:
    """Повторяет асинхронную функцию с экспоненциальной задержкой."""
    last_exception = None
    for attempt in range(1, retries + 1):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            wait = delay * (backoff ** (attempt - 1))
            logger.warning(
                f"Attempt {attempt}/{retries} failed: {e}. Retrying in {wait:.1f}s..."
            )
            await asyncio.sleep(wait)
    raise last_exception


async def retry_forever(
    func: Callable[[], Awaitable[T]],
    delay: float = 3.0,
    backoff: float = 1.5,
    exceptions: tuple = (Exception,),
) -> T:
    """Повторяет функцию бесконечно, пока не будет успеха."""
    attempt = 1
    while True:
        try:
            return await func()
        except exceptions as e:
            wait = min(delay * (backoff ** (attempt - 1)), 60)  # ограничим 60 сек
            logger.warning(
                f"Attempt {attempt} failed: {e}. Retrying in {wait:.1f}s..."
            )
            await asyncio.sleep(wait)
            attempt += 1