import pytest
from time import monotonic
from unittest.mock import AsyncMock, patch
from app.services.steam_client import RateLimiter, SteamClient

class TestRateLimiter:
    async def test_acquire_allows_up_to_rate(self):
        limiter = RateLimiter(5, period=60)
        for _ in range(5):
            await limiter.acquire()
        # 6-й запрос должен ждать
        with patch('asyncio.sleep', return_value=None) as mock_sleep:
            await limiter.acquire()
            mock_sleep.assert_called_once()

    async def test_tokens_refill(self):
        limiter = RateLimiter(2, period=60)
        await limiter.acquire()
        await limiter.acquire()

        # Имитируем прошествие 30 секунд
        limiter.updated_at = monotonic() - 30

        # Теперь должен быть 1 токен (2*30/60 = 1)
        assert limiter.tokens == 0   # после двух acquire токены исчерпаны
        await limiter.acquire()      # это вызовет пополнение и использование токена
        assert limiter.tokens == 0   # после использования снова 0

        # Проверяем, что sleep не вызывался, так как токен был доступен
        with patch('asyncio.sleep', return_value=None) as mock_sleep:
            await limiter.acquire()  # здесь уже недостаточно токенов, должен ждать
            mock_sleep.assert_called_once()

class TestSteamClient:
    async def test_get_price_overview_delegates(self, mock_steam_client):
        data = await mock_steam_client.get_price_overview(730, "Test Item")
        mock_steam_client._provider.get_price_overview.assert_called_with(730, "Test Item")
        assert data["success"] is True

    async def test_get_price_history_delegates(self, mock_steam_client):
        history = await mock_steam_client.get_price_history(730, "Test Item")
        mock_steam_client._provider.get_price_history.assert_called_with(730, "Test Item")
        assert len(history) == 1

    async def test_get_inventory_delegates(self, mock_steam_client):
        inv = await mock_steam_client.get_inventory(123, 730)
        mock_steam_client._provider.get_inventory.assert_called_with(123, 730)
        assert inv["success"] is True

    async def test_close(self, mock_steam_client):
        await mock_steam_client.close()
        mock_steam_client._provider.close.assert_called_once()