import pytest
from telegram import Update
from bot import start, help_command, echo

# Используем asyncio-маркер для всех тестов в модуле
pytestmark = pytest.mark.asyncio

async def test_start(mocker):
    mock_message = mocker.AsyncMock()
    mock_message.text = "/start"

    update = Update(update_id=1, message=mock_message)

    await start(update, None)

    mock_message.reply_text.assert_called_once_with("Привет! Я бот, который помогает отслеживать цены на ваши CS2 предметы")

async def test_help_command(mocker):
    mock_message = mocker.AsyncMock()
    mock_message.text = "/help"

    update = Update(update_id=1, message=mock_message)

    await help_command(update, None)

    mock_message.reply_text.assert_called_once_with("Здесь должна быть вспомогательная информация")

async def test_echo(mocker):
    mock_message = mocker.AsyncMock()
    mock_message.text = "Hello, world!"

    update = Update(update_id=1, message=mock_message)

    mock_reply = mocker.patch.object(update.message, 'reply_text', new_callable=mocker.AsyncMock)

    await echo(update, None)

    mock_reply.assert_called_once_with("Твое сообщение: Hello, world!")

async def test_echo_no_text(mocker):
    mock_message = mocker.AsyncMock()
    mock_message.text = None

    update = Update(update_id=1, message=mock_message)

    await echo(update, None)

    mock_message.reply_text.assert_called_once_with("Я понимаю только текст")