import pytest
from unittest.mock import AsyncMock
import redis.asyncio as redis
from app.bot.cleanup import CleanupManager, CATEGORY_TEMP

@pytest.fixture
def mock_redis():
    r = AsyncMock(spec=redis.Redis)
    r.rpush = AsyncMock()
    r.lrange = AsyncMock(return_value=[b'1', b'2'])
    r.delete = AsyncMock()
    return r

@pytest.fixture
def cleanup(mock_redis):
    return CleanupManager(mock_redis)

async def test_register_message(cleanup, mock_redis):
    await cleanup.register_message(chat_id=1, message_id=10, category=CATEGORY_TEMP)
    mock_redis.rpush.assert_called_with("cleanup:1:temporary", 10)

async def test_clear_messages(cleanup, mock_redis):
    bot = AsyncMock()
    await cleanup.clear_messages(chat_id=1, category=CATEGORY_TEMP, bot=bot)
    mock_redis.lrange.assert_called_with("cleanup:1:temporary", 0, -1)
    assert bot.delete_message.call_count == 2
    mock_redis.delete.assert_called_with("cleanup:1:temporary")

async def test_replace_message(cleanup, mock_redis):
    bot = AsyncMock()
    await cleanup.replace_message(chat_id=1, message_id=20, category=CATEGORY_TEMP, bot=bot)
    # Должен вызвать clear_messages и register_message
    mock_redis.lrange.assert_called()
    mock_redis.rpush.assert_called_with("cleanup:1:temporary", 20)