import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from app.services.steam_client import RateLimiter, SteamClient
from aiosteampy.transport.exceptions import NetworkError


class TestRateLimiter:
    async def test_acquire_allows_up_to_rate(self):
        limiter = RateLimiter(5, period=60)
        # Быстро запрашиваем 5 разрешений – должны пройти без задержки
        for _ in range(5):
            await limiter.acquire()
        # 6-й запрос заставит подождать
        with patch('asyncio.sleep', return_value=None) as mock_sleep:
            await limiter.acquire()
            mock_sleep.assert_called_once()
    
    async def test_tokens_refill(self):
        limiter = RateLimiter(2, period=60)
        await limiter.acquire()
        await limiter.acquire()
        # Имитируем прошествие времени
        limiter.updated_at = asyncio.get_event_loop().time() - 30  # 30 секунд назад
        # теперь должен быть 1 токен (2*30/60 = 1)
        await limiter.acquire()
        # Следующий запрос должен ждать
        with patch('asyncio.sleep', return_value=None) as mock_sleep:
            await limiter.acquire()
            mock_sleep.assert_called_once()

class TestSteamClient:
    async def test_get_price_overview_success(self, steam_client_mock):
        # Настраиваем возвращаемое значение
        steam_client_mock._provider.get_price_overview.return_value = {
            "success": True,
            "lowest_price": "$1.23",
            "median_price": "$2.34",
            "volume": "123"
        }
        
        data = await steam_client_mock.get_price_overview(730, "Test Item")
        assert data["success"] is True
        assert data["lowest_price"] == "$1.23"
        steam_client_mock._provider.get_price_overview.assert_called_with(730, "Test Item")
    
    async def test_get_price_history(self, steam_client_mock):
        steam_client_mock._provider.get_price_history.return_value = [
            ["Jan 01 2026", 1.23, "100"]
        ]
        history = await steam_client_mock.get_price_history(730, "Test Item")
        assert len(history) == 1
        assert history[0][1] == 1.23
    
    async def test_get_inventory(self, steam_client_mock):
        steam_client_mock._provider.get_inventory.return_value = {
            "success": True,
            "rgInventory": {},
            "rgDescriptions": {}
        }
        inv = await steam_client_mock.get_inventory(123456, 730)
        assert inv["success"] is True