from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app import state
from app.config import settings
from app.main import lifespan


@pytest.fixture
def fresh_app():
    """Пустое FastAPI-приложение, чтобы не тащить реальный роутинг."""
    return FastAPI()


@pytest.fixture(autouse=True)
def reset_state():
    """Сбрасываем глобалы до и после теста, чтобы не влиять на другие."""
    saved = (state.redis_client, state.steam_client, state.cleanup_manager)
    state.redis_client = None
    state.steam_client = None
    state.cleanup_manager = None
    yield
    state.redis_client, state.steam_client, state.cleanup_manager = saved


async def test_lifespan_initializes_and_shuts_down(fresh_app):
    mock_redis = AsyncMock()
    mock_redis.close = AsyncMock()

    mock_provider = AsyncMock()
    mock_provider.initialize = AsyncMock()

    mock_steam_client = AsyncMock()
    mock_steam_client.close = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.session = AsyncMock()
    mock_bot.set_webhook = AsyncMock()
    mock_bot.get_webhook_info = AsyncMock(
        return_value=MagicMock(url=f"{settings.WEBHOOK_URL}/webhook")
    )
    mock_bot.delete_webhook = AsyncMock()

    with (
        patch("app.main.redis.from_url", return_value=mock_redis),
        patch("app.main.create_steam_provider", return_value=mock_provider),
        patch("app.main.SteamClient", return_value=mock_steam_client),
        patch("app.main.init_scheduler", new_callable=AsyncMock) as mock_init_sched,
        patch(
            "app.main.shutdown_scheduler", new_callable=AsyncMock
        ) as mock_shutdown_sched,
        patch("app.main.retry_forever", new_callable=AsyncMock) as mock_retry_forever,
        patch("app.main.retry_async", new_callable=AsyncMock) as mock_retry_async,
        patch("app.main.bot_module.bot", mock_bot),
    ):
        async with lifespan(fresh_app):
            # Инициализация
            assert state.redis_client is mock_redis
            assert state.steam_client is mock_steam_client
            assert state.cleanup_manager is not None
            mock_provider.initialize.assert_awaited_once()
            mock_init_sched.assert_awaited_once()
            mock_retry_forever.assert_awaited_once()

        # Остановка: порядок shutdown -> steam -> redis -> bot.session
        mock_shutdown_sched.assert_awaited_once()
        mock_steam_client.close.assert_awaited_once()
        mock_redis.close.assert_awaited_once()
        mock_bot.session.close.assert_awaited_once()
        mock_retry_async.assert_awaited_once()


async def test_lifespan_survives_shutdown_errors(fresh_app):
    """Ошибка при закрытии одного ресурса не должна ломать остальные."""
    mock_redis = AsyncMock()
    mock_redis.close = AsyncMock(side_effect=RuntimeError("redis close fail"))

    mock_steam_client = AsyncMock()
    mock_steam_client.close = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.session = AsyncMock()
    mock_bot.set_webhook = AsyncMock()
    mock_bot.get_webhook_info = AsyncMock(
        return_value=MagicMock(url=f"{settings.WEBHOOK_URL}/webhook")
    )
    mock_bot.delete_webhook = AsyncMock()

    with (
        patch("app.main.redis.from_url", return_value=mock_redis),
        patch("app.main.create_steam_provider", return_value=AsyncMock()),
        patch("app.main.SteamClient", return_value=mock_steam_client),
        patch("app.main.init_scheduler", new_callable=AsyncMock),
        patch("app.main.shutdown_scheduler", new_callable=AsyncMock),
        patch("app.main.retry_forever", new_callable=AsyncMock),
        patch("app.main.retry_async", new_callable=AsyncMock),
        patch("app.main.bot_module.bot", mock_bot),
    ):
        async with lifespan(fresh_app):
            pass

    # Steam и bot всё равно закрыты, несмотря на ошибку Redis
    mock_steam_client.close.assert_awaited_once()
    mock_bot.session.close.assert_awaited_once()


async def test_lifespan_webhook_setup_failure_propagates(fresh_app):
    """Если retry_forever не смог поставить webhook — приложение не стартует."""
    mock_bot = MagicMock()
    mock_bot.session = AsyncMock()

    with (
        patch("app.main.redis.from_url", return_value=AsyncMock()),
        patch("app.main.create_steam_provider", return_value=AsyncMock()),
        patch("app.main.SteamClient", return_value=AsyncMock()),
        patch("app.main.init_scheduler", new_callable=AsyncMock),
        patch(
            "app.main.retry_forever",
            new_callable=AsyncMock,
            side_effect=RuntimeError("webhook failed"),
        ),
        patch("app.main.bot_module.bot", mock_bot),
        pytest.raises(RuntimeError, match="webhook failed"),
    ):
        async with lifespan(fresh_app):
            pass
