from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis
from aiogram import Bot


@pytest.fixture
def mock_session():
    """Мок AsyncSession для подмены БД."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=0)
    session.scalars = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    execute_result = MagicMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    scalars_result.one_or_none.return_value = None
    execute_result.scalars.return_value = scalars_result
    execute_result.scalar_one_or_none.return_value = None
    session.execute.return_value = execute_result

    return session


@pytest.fixture
def mock_redis():
    """Мок Redis клиента."""
    r = AsyncMock(spec=redis.Redis)
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    r.scan = AsyncMock(return_value=(0, []))
    r.delete = AsyncMock()
    return r


@pytest.fixture
def mock_steam_provider():
    """Мок ISteamProvider."""
    provider = AsyncMock()
    provider.initialize = AsyncMock()
    provider.ensure_authenticated = AsyncMock(return_value=True)
    provider.get_price_overview = AsyncMock(
        return_value={
            "success": True,
            "lowest_price": "$1.23",
            "median_price": "$2.34",
            "volume": "100",
        }
    )
    provider.get_price_history = AsyncMock(return_value=[["Jan 01 2026", 1.23, "100"]])
    provider.get_inventory = AsyncMock(
        return_value={"success": True, "rgInventory": {}, "rgDescriptions": {}}
    )
    provider.close = AsyncMock()
    return provider


@pytest.fixture
def mock_steam_client(mock_steam_provider):
    """Мок SteamClient, использующий мок провайдера."""
    from app.services.steam_client import SteamClient

    client = SteamClient(mock_steam_provider)
    # Подменяем RateLimiter, чтобы не ждать
    client._rate_limiter = AsyncMock()
    return client


@pytest.fixture
def mock_bot():
    """Мок aiogram Bot с AsyncMock сессией."""
    bot = MagicMock(spec=Bot)
    bot.session = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


@pytest.fixture
def mock_send_telegram_message():
    """Мок функции отправки сообщения."""
    with patch(
        "app.services.notifier.send_telegram_message", new_callable=AsyncMock
    ) as mock:
        yield mock


@pytest.fixture
def mock_db(mock_session):
    """Патчит get_db на генератор, возвращающий мок-сессию."""

    async def fake_get_db():
        yield mock_session

    with patch("app.bot.dispatcher.get_db", fake_get_db):
        yield mock_session
