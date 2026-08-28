import asyncio
import json
import time
import logging
import httpx
from app.config import settings

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
                self.tokens = 0
            else:
                self.tokens -= 1

class SteamClient:
    def __init__(self, cookies: str = None):
        self.cookies = cookies or settings.STEAM_COOKIES
        self.rate_limiter = RateLimiter(20)  # 20 запросов в минуту
        self.client = httpx.AsyncClient(timeout=30.0)

    async def _request(self, url: str, params: dict = None, use_cookies: bool = True) -> dict:
        await self.rate_limiter.acquire()
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
        }
        if use_cookies and self.cookies:
            headers["Cookie"] = self.cookies
        for attempt in range(3):
            try:
                response = await self.client.get(url, params=params, headers=headers)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(f"429 Too Many Requests, retrying after {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError:
                    logger.error(f"Response is not JSON: {response.text[:200]}")
                    return {}
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error {e.response.status_code} for {url}")
                raise
            except Exception as e:
                logger.error(f"Request failed: {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        return {}

    async def get_price_overview(self, app_id: int, market_hash_name: str) -> dict:
        url = "https://steamcommunity.com/market/priceoverview/"
        params = {
            "appid": app_id,
            "currency": 1,
            "market_hash_name": market_hash_name
        }
        data = await self._request(url, params)
        return data

    async def get_price_history(self, app_id: int, market_hash_name: str) -> list:
        url = "https://steamcommunity.com/market/pricehistory/"
        params = {
            "appid": app_id,
            "market_hash_name": market_hash_name
        }
        data = await self._request(url, params)
        return data.get("prices", [])

    async def get_inventory(self, steam_id64: int, app_id: int) -> dict:
        # Используем эндпоинт из правок
        url = f"https://steamcommunity.com/profiles/{steam_id64}/inventory/json/{app_id}/2"
        data = await self._request(url)
        return data

    async def close(self):
        await self.client.aclose()

# Глобальный экземпляр клиента создается в lifespan