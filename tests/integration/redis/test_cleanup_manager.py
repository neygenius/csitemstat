from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from app.bot.cleanup import CATEGORY_TEMP, CleanupManager


@pytest.fixture
def cleanup_manager(redis_client):
    return CleanupManager(redis_client)


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


async def test_register_message_appends_to_list(cleanup_manager, redis_client):
    await cleanup_manager.register_message(
        chat_id=1, message_id=10, category=CATEGORY_TEMP
    )
    await cleanup_manager.register_message(
        chat_id=1, message_id=11, category=CATEGORY_TEMP
    )

    values = await redis_client.lrange("cleanup:1:temporary", 0, -1)
    assert [int(v) for v in values] == [10, 11]


async def test_clear_messages_deletes_and_wipes_list(
    cleanup_manager, mock_bot, redis_client
):
    await cleanup_manager.register_message(
        chat_id=1, message_id=10, category=CATEGORY_TEMP
    )
    await cleanup_manager.register_message(
        chat_id=1, message_id=11, category=CATEGORY_TEMP
    )

    await cleanup_manager.clear_messages(
        chat_id=1, category=CATEGORY_TEMP, bot=mock_bot
    )

    assert mock_bot.delete_message.await_count == 2
    assert await redis_client.exists("cleanup:1:temporary") == 0


async def test_clear_messages_noop_when_empty(cleanup_manager, mock_bot):
    await cleanup_manager.clear_messages(
        chat_id=99, category=CATEGORY_TEMP, bot=mock_bot
    )
    mock_bot.delete_message.assert_not_awaited()


async def test_replace_message_clears_old_and_registers_new(
    cleanup_manager, mock_bot, redis_client
):
    await cleanup_manager.register_message(
        chat_id=1, message_id=10, category=CATEGORY_TEMP
    )

    await cleanup_manager.replace_message(
        chat_id=1, message_id=20, category=CATEGORY_TEMP, bot=mock_bot
    )

    values = await redis_client.lrange("cleanup:1:temporary", 0, -1)
    assert [int(v) for v in values] == [20]
    mock_bot.delete_message.assert_awaited_once_with(1, 10)


async def test_clear_messages_continues_on_delete_error(
    cleanup_manager, mock_bot, redis_client
):
    """Ошибка удаления одного сообщения не прерывает очистку остальных."""
    await cleanup_manager.register_message(
        chat_id=1, message_id=10, category=CATEGORY_TEMP
    )
    await cleanup_manager.register_message(
        chat_id=1, message_id=11, category=CATEGORY_TEMP
    )

    bad = TelegramBadRequest(method=MagicMock(), message="not found")
    mock_bot.delete_message = AsyncMock(side_effect=[bad, None])

    await cleanup_manager.clear_messages(
        chat_id=1, category=CATEGORY_TEMP, bot=mock_bot
    )

    assert mock_bot.delete_message.await_count == 2
    # Ключ всё равно удалён, даже если один delete упал
    assert await redis_client.exists("cleanup:1:temporary") == 0


async def test_categories_are_isolated(cleanup_manager, redis_client):
    await cleanup_manager.register_message(
        chat_id=1, message_id=10, category="temporary"
    )
    await cleanup_manager.register_message(chat_id=1, message_id=20, category="pinned")

    temp = await redis_client.lrange("cleanup:1:temporary", 0, -1)
    pinned = await redis_client.lrange("cleanup:1:pinned", 0, -1)
    assert [int(v) for v in temp] == [10]
    assert [int(v) for v in pinned] == [20]
