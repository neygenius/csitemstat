import asyncio
import logging
import time
from typing import Any, Dict, List

from app.services.steam.interface import ISteamProvider

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, rate: int, period: float = 60.0):
        self.rate = rate
        self.period = period
        self.tokens = rate
        self.updated_at = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.updated_at
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.period))
            self.updated_at = now
            if self.tokens < 1:
                wait = (1 - self.tokens) * (self.period / self.rate)
                logger.debug(f"Rate limit: waiting {wait:.2f}s")
                await asyncio.sleep(wait)
                now = time.monotonic()
                self.tokens = 0
                self.updated_at = now
            else:
                self.tokens -= 1


class SteamClient:
    """
    Фасад, делегирующий вызовы провайдеру.
    """

    def __init__(self, provider: ISteamProvider):
        self._provider = provider
        self._rate_limiter = RateLimiter(20)

    async def get_price_overview(self, app_id: int, market_hash_name: str) -> Dict[str, Any]:
        await self._rate_limiter.acquire()
        return await self._provider.get_price_overview(app_id, market_hash_name)

    async def get_price_history(self, app_id: int, market_hash_name: str) -> List[List]:
        await self._rate_limiter.acquire()
        return await self._provider.get_price_history(app_id, market_hash_name)

    async def get_inventory(self, steam_id64: int, app_id: int) -> Dict[str, Any]:
        await self._rate_limiter.acquire()
        return await self._provider.get_inventory(steam_id64, app_id)

    async def close(self) -> None:
        await self._provider.close()