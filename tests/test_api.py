import os
import pytest
from telegram import Bot
from telegram.error import TelegramError

# Используем asyncio-маркер для всех тестов в модуле
pytestmark = pytest.mark.asyncio

@pytest.mark.skipif(
    not os.getenv("BOT_TOKEN"),
    reason="BOT_TOKEN not set in environment"
)
async def test_bot_token_valid():
    """Проверяем, что токен валиден и бот существует"""
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    me = await bot.get_me()
    assert me.is_bot is True
    assert me.username is not None
    assert me.username.endswith("bot")

@pytest.mark.skipif(
    not os.getenv("BOT_TOKEN") or not os.getenv("CHAT_ID"),
    reason="BOT_TOKEN or CHAT_ID not set"
)
async def test_send_message():
    """Проверяем возможность отправить сообщение через API"""
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    chat_id = os.getenv("CHAT_ID")
    try:
        msg = await bot.send_message(chat_id=chat_id, text="Тестовое сообщение от pytest")
        assert msg.message_id is not None
        assert msg.text == "Тестовое сообщение от pytest"
    except TelegramError as e:
        pytest.fail(f"Не удалось отправить сообщение: {e}")