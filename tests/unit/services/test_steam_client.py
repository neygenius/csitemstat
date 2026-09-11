import asyncio
from unittest.mock import patch

from app.services.steam_client import RateLimiter


class TestRateLimiter:
    async def test_acquire_allows_up_to_rate(self):
        limiter = RateLimiter(5, period=60)
        for _ in range(5):
            await limiter.acquire()
        # 6-й запрос должен ждать
        with patch("asyncio.sleep", return_value=None) as mock_sleep:
            await limiter.acquire()
            mock_sleep.assert_called_once()

    async def test_tokens_refill(self, mocker):
        limiter = RateLimiter(2, period=60)
        # Оба токена уже использованы
        limiter.tokens = 0
        limiter.updated_at = 0

        mocker.patch("time.monotonic", return_value=30)
        with patch("asyncio.sleep", return_value=None) as mock_sleep:
            await limiter.acquire()

        # За 30 секунд при rate=2 и period=60 получаем 1 токен
        # sleep не вызывается, а токен используется
        mock_sleep.assert_not_called()
        assert limiter.tokens == 0

    async def test_concurrent_acquire_serialized_by_lock(self):
        """Параллельные вызовы не должны приводить к превышению лимита."""
        limiter = RateLimiter(rate=3, period=60.0)
        sleep_calls = []

        async def fake_sleep(s):
            sleep_calls.append(s)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await asyncio.gather(*(limiter.acquire() for _ in range(6)))

        # Из 6 вызовов минимум 3 должны были "поспать"
        assert len(sleep_calls) >= 3


class TestSteamClient:
    async def test_get_price_overview_delegates(self, mock_steam_client):
        data = await mock_steam_client.get_price_overview(730, "Test Item")
        mock_steam_client._provider.get_price_overview.assert_called_with(
            730, "Test Item"
        )
        assert data["success"] is True

    async def test_get_price_history_delegates(self, mock_steam_client):
        history = await mock_steam_client.get_price_history(730, "Test Item")
        mock_steam_client._provider.get_price_history.assert_called_with(
            730, "Test Item"
        )
        assert len(history) == 1

    async def test_get_inventory_delegates(self, mock_steam_client):
        inv = await mock_steam_client.get_inventory(123, 730)
        mock_steam_client._provider.get_inventory.assert_called_with(123, 730)
        assert inv["success"] is True

    async def test_close(self, mock_steam_client):
        await mock_steam_client.close()
        mock_steam_client._provider.close.assert_called_once()
