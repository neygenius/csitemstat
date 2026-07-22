import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from app.services.steam_client import RateLimiter, SteamClient

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
    @pytest.fixture
    async def client(self):
        client = SteamClient()
        yield client
        await client.close()

    @patch('httpx.AsyncClient.get')
    async def test_get_price_overview_success(self, mock_get, client):
        mock_get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"success": True, "lowest_price": "$1.23", "median_price": "$2.34", "volume": "123"}
        )
        data = await client.get_price_overview(730, "Test Item")
        assert data["success"]
        assert data["lowest_price"] == "$1.23"

    @patch('httpx.AsyncClient.get')
    async def test_get_price_overview_429_retry(self, mock_get, client):
        mock_get.return_value = AsyncMock(status_code=429, headers={"Retry-After": "1"})
        with patch('asyncio.sleep', return_value=None) as mock_sleep:
            data = await client.get_price_overview(730, "Item")
            mock_sleep.assert_called()
            # После 429, клиент попробует ещё раз (всего 3 попытки), но так как ответ всегда 429,
            # в итоге вернётся пустой словарь (последняя попытка вернёт тот же 429, но мы не обработали)
            # Уточним логику: в коде при 429 делается sleep и continue, а после всех попыток возвращается {}.
            # Значит вызов sleep должен произойти 2 раза (после первой и второй попытки), вернётся {}
            assert mock_sleep.call_count == 3
            assert data == {}

    @patch('httpx.AsyncClient.get')
    async def test_get_price_history(self, mock_get, client):
        mock_get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"prices": [["Jul 20 2026 01: +0", 10.5, "100"]]}
        )
        history = await client.get_price_history(730, "Item")
        assert len(history) == 1
        assert history[0][1] == 10.5

    @patch('httpx.AsyncClient.get')
    async def test_get_inventory(self, mock_get, client):
        mock_get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "success": True,
                "rgInventory": {"1": {"classid": "100", "instanceid": "200"}},
                "rgDescriptions": {"100_200": {"market_hash_name": "Test Item"}}
            }
        )
        inv = await client.get_inventory(76561198000000000, 730)
        assert inv["success"]
        assert "Test Item" in inv["rgDescriptions"]["100_200"]["market_hash_name"]