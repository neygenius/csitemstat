import pytest
from unittest.mock import AsyncMock, patch
from aiogram import Bot
from aiogram.types import Message, User as TGUser, Chat, Update
from datetime import datetime
from sqlalchemy import select
from app.bot.dispatcher import dp
from app.config import settings
from app.db.models import User, Item, UserTrackedItem
from app.services.crypto import decrypt_steam_id

def make_message(user_id: int, text: str) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=TGUser(id=user_id, is_bot=False, first_name="Test"),
        text=text,
    )

@pytest.fixture
def mock_bot():
    bot = Bot(token=settings.BOT_TOKEN)
    # Подменяем сессию на AsyncMock (вызываемый объект)
    bot.session = AsyncMock()
    return bot

@pytest.mark.asyncio
async def test_start_command(session, mock_bot):
    user_id = 123456

    async def fake_get_db():
        yield session

    with patch('app.bot.dispatcher.get_db', fake_get_db):
        message = make_message(user_id, "/start")
        await dp.feed_update(mock_bot, Update(update_id=1, message=message))

    # Пользователь создан
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    assert user is not None

    # Проверяем, что сессия вызвана хотя бы один раз (отправка сообщения)
    mock_bot.session.assert_called()
    call_args = mock_bot.session.call_args
    # call_args: (bot, method), где method – SendMessage
    assert call_args[0][1].chat_id == user_id
    assert "Добро пожаловать" in call_args[0][1].text
    await mock_bot.session.close()

@pytest.mark.asyncio
async def test_link_steam_flow(session, mock_bot):
    user_id = 2000
    session.add(User(id=user_id, chat_id=user_id))
    await session.commit()

    async def fake_get_db():
        yield session

    with patch('app.bot.dispatcher.get_db', fake_get_db):
        # Шаг 1: /link_steam
        msg1 = make_message(user_id, "/link_steam")
        await dp.feed_update(mock_bot, Update(update_id=2, message=msg1))
        mock_bot.session.assert_called()
        call_args = mock_bot.session.call_args
        assert call_args[0][1].chat_id == user_id
        assert "Неверный формат: SteamID64" in call_args[0][1].text

        # Шаг 2: ввод steam id
        msg2 = make_message(user_id, "76561198000000000")
        await dp.feed_update(mock_bot, Update(update_id=3, message=msg2))
        mock_bot.session.assert_called()
        call_args = mock_bot.session.call_args
        assert call_args[0][1].chat_id == user_id
        assert "✅ Steam ID успешно привязан!" in call_args[0][1].text

    # Проверяем сохранение в БД
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    decrypted = decrypt_steam_id(user.steam_id64)
    assert decrypted == 76561198000000000
    await mock_bot.session.close()

@pytest.mark.asyncio
async def test_inventory_without_steam(session, mock_bot):
    user_id = 3000
    session.add(User(id=user_id, chat_id=user_id))
    await session.commit()

    async def fake_get_db():
        yield session

    with patch('app.bot.dispatcher.get_db', fake_get_db):
        msg = make_message(user_id, "/inventory")
        await dp.feed_update(mock_bot, Update(update_id=4, message=msg))

    mock_bot.session.assert_called()
    call_args = mock_bot.session.call_args
    assert "привяжите Steam ID" in call_args[0][1].text
    await mock_bot.session.close()

@pytest.mark.asyncio
async def test_track_item(session, mock_bot):
    user_id = 4000
    session.add(User(id=user_id, chat_id=user_id))
    item = Item(app_id=730, market_hash_name="TestTrackItem", name="TestTrackItem")
    session.add(item)
    await session.commit()
    item_id = item.id

    async def fake_get_db():
        yield session

    with patch('app.bot.dispatcher.get_db', fake_get_db):
        msg = make_message(user_id, "/track TestTrackItem")
        await dp.feed_update(mock_bot, Update(update_id=5, message=msg))

    # Проверяем, что связь создана
    result = await session.execute(
        select(UserTrackedItem).where(
            UserTrackedItem.user_id == user_id,
            UserTrackedItem.item_id == item_id
        )
    )
    assert result.scalar_one_or_none() is not None

    # Проверяем, что сообщение отправлено
    mock_bot.session.assert_called()
    call_args = mock_bot.session.call_args
    assert "добавлен в портфель" in call_args[0][1].text
    await mock_bot.session.close()