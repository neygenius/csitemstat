from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message
from aiogram.types import User as TGUser
from sqlalchemy import select

from app.bot.dispatcher import cmd_inventory, cmd_portfolio, cmd_start, cmd_track
from app.db.models import Item, User, UserTrackedItem


def make_message(user_id: int, text: str) -> Message:
    msg = MagicMock(spec=Message)
    msg.message_id = 1
    msg.date = datetime.now(tz=timezone.utc)
    msg.chat = Chat(id=user_id, type="private")
    msg.from_user = TGUser(id=user_id, is_bot=False, first_name="Test")
    msg.text = text
    msg.answer = AsyncMock(return_value=MagicMock(message_id=100))
    msg.delete = AsyncMock()
    return msg


@pytest.fixture
def patch_db(session):
    async def fake_get_db():
        yield session

    with patch("app.bot.dispatcher.get_db", fake_get_db):
        yield


@pytest.fixture(autouse=True)
def patch_cleanup():
    with patch("app.bot.dispatcher.app_state.cleanup_manager", None):
        yield


async def test_cmd_start_creates_user_in_db(patch_db, session):
    msg = make_message(12345, "/start")
    msg.answer = AsyncMock(return_value=MagicMock(message_id=100))

    await cmd_start(msg)

    user = await session.get(User, 12345)
    assert user is not None
    assert user.chat_id == 12345
    msg.answer.assert_awaited_once()


async def test_cmd_start_idempotent(patch_db, session):
    msg = make_message(12345, "/start")
    msg.answer = AsyncMock(return_value=MagicMock(message_id=100))

    await cmd_start(msg)
    await cmd_start(msg)

    # Пользователь не дублируется
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1


async def test_cmd_track_creates_user_tracked_item(patch_db, session):
    session.add(User(id=1, chat_id=1))
    session.add(Item(app_id=730, market_hash_name="AK-47", name="AK-47"))
    await session.commit()

    msg = make_message(1, "/track AK-47")
    msg.answer = AsyncMock(return_value=MagicMock(message_id=100))

    await cmd_track(msg)

    tracked = (await session.execute(select(UserTrackedItem))).scalars().all()
    assert len(tracked) == 1
    assert tracked[0].user_id == 1


async def test_cmd_track_already_tracked(patch_db, session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()
    session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
    await session.commit()

    msg = make_message(1, "/track AK-47")
    msg.answer = AsyncMock(return_value=MagicMock(message_id=100))

    await cmd_track(msg)

    # Дубликат не создан
    tracked = (await session.execute(select(UserTrackedItem))).scalars().all()
    assert len(tracked) == 1
    # Пользователь получил уведомление
    assert "уже в вашем портфеле" in msg.answer.call_args[0][0]


async def test_cmd_portfolio_lists_tracked_items(patch_db, session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()
    session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
    await session.commit()

    msg = make_message(1, "/bagpack")
    msg.answer = AsyncMock(return_value=MagicMock(message_id=100))

    await cmd_portfolio(msg)

    msg.answer.assert_awaited_once()

    text = msg.answer.call_args.args[0]
    assert "портфель" in text.lower()

    keyboard = msg.answer.call_args.kwargs["reply_markup"]
    button_texts = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert any("AK-47" in t for t in button_texts)


async def test_cmd_portfolio_empty(patch_db, session):
    session.add(User(id=1, chat_id=1))
    await session.commit()

    msg = make_message(1, "/bagpack")
    msg.answer = AsyncMock(return_value=MagicMock(message_id=100))

    await cmd_portfolio(msg)

    assert "портфель пуст" in msg.answer.call_args[0][0]


async def test_steam_client_survives_multiple_commands(patch_db, session):
    """Глобальный SteamClient не должен закрываться в хендлере."""
    session.add(User(id=1, chat_id=1, steam_id64=b"enc"))
    await session.commit()

    fake_client = AsyncMock()
    fake_client.close = AsyncMock()

    with (
        patch("app.bot.dispatcher.app_state.steam_client", fake_client),
        patch("app.bot.dispatcher.decrypt_steam_id", return_value=76561198000000000),
        patch(
            "app.bot.dispatcher.fetch_grouped_inventory",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        msg1 = make_message(1, "/inventory")
        await cmd_inventory(msg1)

        msg2 = make_message(1, "/inventory")
        await cmd_inventory(msg2)

    # Клиент не должен быть закрыт в хендлере
    fake_client.close.assert_not_awaited()
