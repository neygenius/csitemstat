import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot, types
from aiogram.fsm.context import FSMContext

from app.bot import dispatcher
from app.bot.dispatcher import (
    cb_add_track,
    cb_alert_add_start,
    cb_alert_period,
    cb_alert_remove,
    cb_inventory_page,
    cb_portfolio_page,
    cb_price_period,
    cb_stats,
    cb_sub_add,
    cb_sub_remove,
    cb_subs,
    cb_tracked_alerts,
    cb_tracked_item,
    cb_tracked_subs,
    cb_tracked_untrack,
    cmd_alert,
    cmd_delete_alert,
    cmd_help,
    cmd_inventory,
    cmd_link_steam,
    cmd_portfolio,
    cmd_start,
    cmd_stats,
    cmd_subscribe,
    cmd_track,
    cmd_unsubscribe,
    cmd_untrack,
    process_alert_percent,
    process_steam_id,
    send_price_chart,
)
from app.db.models import (
    Item,
    ItemDailyStats,
    ItemHourlyStats,
    ItemSnapshot,
    PriceAlert,
    Subscription,
    User,
    UserTrackedItem,
)

# -----------------------------------------------------------------------------
# Вспомогательные фикстуры и утилиты
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_bot():
    """Мок Bot, у которого session — AsyncMock (для отправки сообщений)."""
    bot = MagicMock(spec=Bot)
    bot.session = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


@pytest.fixture
def mock_message():
    """Создаёт Message с минимально необходимыми атрибутами."""
    msg = MagicMock(spec=types.Message)
    msg.message_id = 1
    msg.from_user = MagicMock()
    msg.from_user.id = 123456789
    msg.chat = MagicMock()
    msg.chat.id = 123456789
    msg.text = ""
    msg.answer = AsyncMock(return_value=MagicMock(message_id=100))
    msg.delete = AsyncMock()
    return msg


@pytest.fixture
def mock_callback_query():
    """Создаёт CallbackQuery с нужными полями."""
    cb = MagicMock(spec=types.CallbackQuery)
    cb.id = "cb1"
    cb.from_user = MagicMock()
    cb.from_user.id = 123456789
    cb.message = MagicMock()
    cb.message.chat.id = 123456789
    cb.message.message_id = 50
    cb.message.answer = AsyncMock(return_value=MagicMock(message_id=101))
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    cb.data = ""
    return cb


@pytest.fixture
def mock_state():
    """Мок FSMContext."""
    state = MagicMock(spec=FSMContext)
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.clear = AsyncMock()
    return state


@pytest.fixture
def mock_app_state():
    """Мокируем глобальные объекты app_state."""
    cleanup_manager = MagicMock()
    cleanup_manager.register_message = AsyncMock()
    cleanup_manager.clear_messages = AsyncMock()
    cleanup_manager.replace_message = AsyncMock()

    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.setex = AsyncMock()

    steam_client = AsyncMock()
    steam_client.get_price_overview = AsyncMock(return_value={"success": True})
    steam_client.get_price_history = AsyncMock(return_value=[])
    steam_client.get_inventory = AsyncMock(
        return_value={"success": True, "rgInventory": {}, "rgDescriptions": {}}
    )
    steam_client.close = AsyncMock()

    with (
        patch("app.bot.dispatcher.app_state.cleanup_manager", cleanup_manager),
        patch("app.bot.dispatcher.app_state.redis_client", redis_client),
        patch("app.bot.dispatcher.app_state.steam_client", steam_client),
    ):
        yield {
            "cleanup_manager": cleanup_manager,
            "redis_client": redis_client,
            "steam_client": steam_client,
        }


# -----------------------------------------------------------------------------
# Тесты команд
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_start_creates_new_user(
    mock_db, mock_bot, mock_message, mock_app_state
):
    mock_db.get = AsyncMock(return_value=None)  # пользователь не найден
    await cmd_start(mock_message)
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_message.answer.assert_called_once()
    args, _ = mock_message.answer.call_args
    assert "Добро пожаловать" in args[0]


@pytest.mark.asyncio
async def test_cmd_start_existing_user(mock_db, mock_bot, mock_message, mock_app_state):
    user = User(id=123456789, chat_id=123456789)
    mock_db.get = AsyncMock(return_value=user)
    await cmd_start(mock_message)
    mock_db.add.assert_not_called()
    mock_message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_help_registers_temp_message(
    mock_db, mock_bot, mock_message, mock_app_state
):
    msg_mock = AsyncMock()
    msg_mock.message_id = 100
    mock_message.answer.return_value = msg_mock

    await cmd_help(mock_message)

    mock_app_state["cleanup_manager"].register_message.assert_called_once_with(
        mock_message.chat.id, msg_mock.message_id, dispatcher.CATEGORY_TEMP
    )


@pytest.mark.asyncio
async def test_cmd_link_steam_sets_state(
    mock_db, mock_bot, mock_message, mock_state, mock_app_state
):
    await cmd_link_steam(mock_message, mock_state)
    mock_state.set_state.assert_called_once()
    mock_message.answer.assert_called_once()
    mock_app_state["cleanup_manager"].register_message.assert_called_once()


@pytest.mark.asyncio
async def test_process_steam_id_invalid(
    mock_db, mock_bot, mock_message, mock_state, mock_app_state
):
    mock_message.text = "не число"
    await process_steam_id(mock_message, mock_state)
    # Проверяем, что сообщение об ошибке отправлено
    assert mock_message.answer.called
    # Состояние не сбрасывается
    mock_state.clear.assert_not_called()


@pytest.mark.asyncio
async def test_process_steam_id_success(
    mock_db, mock_bot, mock_message, mock_state, mock_app_state
):
    mock_message.text = "76561198000000000"
    user = User(id=123456789, chat_id=123456789)
    mock_db.get = AsyncMock(return_value=user)

    await process_steam_id(mock_message, mock_state)

    # Проверяем, что пользователь обновлён
    assert user.steam_id64 is not None  # предполагаем, что шифрование работает
    mock_db.commit.assert_called_once()
    mock_state.clear.assert_called_once()
    mock_message.delete.assert_called_once()
    mock_message.answer.assert_called_once()
    mock_app_state["cleanup_manager"].replace_message.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_inventory_without_steam(
    mock_db, mock_bot, mock_message, mock_app_state
):
    user = User(id=123456789, chat_id=123456789, steam_id64=None)
    mock_db.get = AsyncMock(return_value=user)
    await cmd_inventory(mock_message)
    # Должно быть сообщение о необходимости привязки
    assert "привяжите Steam ID" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_inventory_with_cache(
    mock_db, mock_bot, mock_message, mock_app_state
):
    user = User(id=123456789, chat_id=123456789, steam_id64=b"encrypted")
    mock_db.get = AsyncMock(return_value=user)
    # Мокаем decrypt_steam_id, чтобы вернуть число
    with patch("app.bot.dispatcher.decrypt_steam_id", return_value=76561198000000000):
        # redis вернёт кэш
        cached = json.dumps([("Item A", 1), ("Item B", 2)])
        mock_app_state["redis_client"].get = AsyncMock(return_value=cached)

        await cmd_inventory(mock_message)

    mock_app_state["redis_client"].get.assert_called_once_with("inv:123456789")
    mock_message.answer.assert_called_once()
    # Проверяем, что сообщение содержит "Инвентарь"
    assert "инвентарь" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_inventory_fetch_error(
    mock_db, mock_bot, mock_message, mock_app_state
):
    user = User(id=123456789, chat_id=123456789, steam_id64=b"encrypted")
    mock_db.get = AsyncMock(return_value=user)
    mock_app_state["steam_client"].get_inventory = AsyncMock(
        side_effect=Exception("Steam error")
    )
    with patch("app.bot.dispatcher.decrypt_steam_id", return_value=76561198000000000):
        await cmd_inventory(mock_message)
    # Должно быть сообщение об ошибке
    assert "Не удалось загрузить" in mock_message.answer.call_args[0][0]
    mock_app_state["steam_client"].close.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_track_single_item(mock_db, mock_bot, mock_message, mock_app_state):
    mock_message.text = "/track AK-47"
    item = Item(id=1, app_id=730, market_hash_name="AK-47", name="AK-47")
    # Мок поиска предмета
    mock_db.execute.return_value.scalars.return_value.all.return_value = [item]

    # Настройка get: для User возвращаем пользователя, для UserTrackedItem – None
    async def mock_get(model, pk):
        if model == User:
            return User(id=123456789, chat_id=123456789)
        return None

    mock_db.get.side_effect = mock_get

    await cmd_track(mock_message)

    mock_db.add.assert_called_once()  # добавлен UserTrackedItem
    mock_db.commit.assert_called_once()
    mock_message.answer.assert_called_once()
    assert "добавлен в портфель" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_bagpack_empty(mock_db, mock_bot, mock_message, mock_app_state):
    user = User(id=123456789, chat_id=123456789)
    mock_db.get = AsyncMock(return_value=user)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    await cmd_portfolio(mock_message)
    assert "портфель пуст" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_bagpack_with_items(mock_db, mock_bot, mock_message, mock_app_state):
    user = User(id=123456789, chat_id=123456789)
    item1 = Item(id=1, app_id=730, market_hash_name="AK-47", name="AK-47")
    item2 = Item(id=2, app_id=730, market_hash_name="M4A4", name="M4A4")
    mock_db.get = AsyncMock(return_value=user)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [item1, item2]
    with patch("app.bot.dispatcher.portfolio_pagination") as mock_pagination:
        mock_pagination.return_value = types.InlineKeyboardMarkup(inline_keyboard=[])
        await cmd_portfolio(mock_message)
    assert mock_message.answer.called
    mock_pagination.assert_called_once_with([item1, item2], 0, 10)


@pytest.mark.asyncio
async def test_cmd_stats_no_item(mock_db, mock_bot, mock_message, mock_app_state):
    mock_message.text = "/stats NonExistent"
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    await cmd_stats(mock_message)
    assert "Предмет не найден" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_stats_multiple_items(
    mock_db, mock_bot, mock_message, mock_app_state
):
    mock_message.text = "/stats AK"
    item1 = Item(id=1, app_id=730, market_hash_name="AK-47", name="AK-47")
    item2 = Item(id=2, app_id=730, market_hash_name="AK-48", name="AK-48")
    mock_db.execute.return_value.scalars.return_value.all.return_value = [item1, item2]
    await cmd_stats(mock_message)
    assert "Найдено несколько предметов" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_stats_snapshot_exists(
    mock_db, mock_bot, mock_message, mock_app_state
):
    mock_message.text = "/stats AK-47"
    item = Item(id=1, app_id=730, market_hash_name="AK-47", name="AK-47")
    snapshot = ItemSnapshot(
        item_id=1,
        median_price=100.0,
        lowest_price=90.0,
        volume_24h=100,
        trend_direction="up",
        price_24h_ago=95.0,
    )
    mock_db.execute.return_value.scalars.return_value.all.return_value = [item]
    mock_db.get = AsyncMock(return_value=snapshot)
    with (
        patch("app.bot.dispatcher.item_actions") as mock_actions,
        patch(
            "app.bot.dispatcher.send_price_chart", new_callable=AsyncMock
        ) as mock_chart,
    ):
        mock_actions.return_value = types.InlineKeyboardMarkup(inline_keyboard=[])
        await cmd_stats(mock_message)
    assert "Медиана" in mock_message.answer.call_args[0][0]
    mock_chart.assert_called_once_with(mock_message.chat.id, item.id, days=30)


@pytest.mark.asyncio
async def test_cmd_stats_no_snapshot_success(
    mock_db, mock_bot, mock_message, mock_app_state
):
    mock_message.text = "/stats AK-47"
    item = Item(id=1, app_id=730, market_hash_name="AK-47", name="AK-47")
    mock_db.execute.return_value.scalars.return_value.all.return_value = [item]

    # Первый вызов get(ItemSnapshot, ...) вернёт None, второй — заполненный snapshot
    snapshot = ItemSnapshot(
        item_id=1,
        lowest_price=90.0,
        median_price=100.0,
        volume_24h=100,
        trend_direction="up",
        price_24h_ago=95.0,
    )
    mock_db.get.side_effect = [None, snapshot]

    with (
        patch(
            "app.bot.dispatcher.update_single_item_snapshot", new_callable=AsyncMock
        ) as mock_update,
        patch(
            "app.bot.dispatcher.send_price_chart", new_callable=AsyncMock
        ) as mock_chart,
    ):
        mock_update.return_value = True

        await cmd_stats(mock_message)

    mock_update.assert_called_once()
    mock_chart.assert_called_once()


# -----------------------------------------------------------------------------
# Тесты callback-обработчиков
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cb_add_track_existing(
    mock_db, mock_bot, mock_callback_query, mock_app_state
):
    mock_callback_query.data = "add_track:AK-47"
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    # В cb_add_track используется scalar_one_or_none()
    mock_db.execute.return_value.scalar_one_or_none.return_value = item

    user = User(id=123456789, chat_id=123456789)

    async def fake_get(model, pk):
        if model == User:
            return user
        if model == UserTrackedItem:
            return UserTrackedItem(user_id=123456789, item_id=1)
        return None

    mock_db.get = AsyncMock(side_effect=fake_get)

    await cb_add_track(mock_callback_query)

    mock_callback_query.answer.assert_called_with("Этот предмет уже в вашем портфеле")
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_cb_add_track_new(mock_db, mock_bot, mock_callback_query, mock_app_state):
    mock_callback_query.data = "add_track:AK-47"
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.execute.return_value.scalars.return_value.one_or_none.return_value = item
    # Пользователь не существует, вернём None
    mock_db.get = AsyncMock(return_value=None)
    await cb_add_track(mock_callback_query)
    mock_db.add.assert_called()  # добавлен UserTrackedItem и, возможно, User
    mock_db.commit.assert_called_once()
    mock_callback_query.answer.assert_called()


@pytest.mark.asyncio
async def test_cb_inventory_page(
    mock_db, mock_bot, mock_callback_query, mock_app_state
):
    mock_callback_query.data = "inv_page:1"
    cached = json.dumps([("Item A", 1), ("Item B", 2), ("Item C", 3)])
    mock_app_state["redis_client"].get = AsyncMock(return_value=cached)
    await cb_inventory_page(mock_callback_query)
    mock_callback_query.message.edit_text.assert_called_once()
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cb_stats(mock_db, mock_bot, mock_callback_query, mock_app_state):
    mock_callback_query.data = "stats:1"
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.get = AsyncMock(return_value=item)
    # Мокаем cmd_stats, чтобы не выполнять полный сценарий
    with patch(
        "app.bot.dispatcher.cmd_stats", new_callable=AsyncMock
    ) as mock_cmd_stats:
        await cb_stats(mock_callback_query)
        mock_cmd_stats.assert_called_once_with(
            mock_callback_query.message, item.market_hash_name
        )


@pytest.mark.asyncio
async def test_cb_sub_add(mock_db, mock_bot, mock_callback_query, mock_app_state):
    mock_callback_query.data = "sub_add:1:daily"
    user = User(id=123456789, chat_id=123456789)
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.get = AsyncMock(
        side_effect=lambda model, pk: user if model == User else item
    )
    # Проверяем, что подписка создаётся
    mock_db.execute.return_value.scalars.return_value.one_or_none.return_value = None
    await cb_sub_add(mock_callback_query)
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cb_portfolio_page(
    mock_db, mock_bot, mock_callback_query, mock_app_state
):
    mock_callback_query.data = "portfolio_page:1"
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.execute.return_value.scalars.return_value.all.return_value = [item]
    with patch("app.bot.dispatcher.portfolio_pagination") as mock_pagination:
        mock_pagination.return_value = types.InlineKeyboardMarkup(inline_keyboard=[])
        await cb_portfolio_page(mock_callback_query)
    mock_callback_query.message.edit_text.assert_called_once()
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cb_tracked_item(mock_db, mock_bot, mock_callback_query, mock_app_state):
    mock_callback_query.data = "tracked_item:1"
    await cb_tracked_item(mock_callback_query)
    mock_callback_query.message.answer.assert_called_once()
    mock_app_state["cleanup_manager"].replace_message.assert_called_once()
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cb_price_period(mock_db, mock_bot, mock_callback_query, mock_app_state):
    mock_callback_query.data = "price_period:1:30"
    with patch(
        "app.bot.dispatcher.send_price_chart", new_callable=AsyncMock
    ) as mock_chart:
        await cb_price_period(mock_callback_query)
    mock_chart.assert_called_once_with(mock_callback_query.message.chat.id, 1, days=30)
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cb_subs(mock_db, mock_bot, mock_callback_query, mock_app_state):
    mock_callback_query.data = "subs:1"
    await cb_subs(mock_callback_query)
    mock_callback_query.message.answer.assert_called_once()
    mock_app_state["cleanup_manager"].replace_message.assert_called_once()
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cb_tracked_subs_no_subs(
    mock_db, mock_bot, mock_callback_query, mock_app_state
):
    mock_callback_query.data = "tracked_subs:1"
    user = User(id=123456789, chat_id=123456789)
    mock_db.get = AsyncMock(return_value=user)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    await cb_tracked_subs(mock_callback_query)
    assert "Ваши подписки" in mock_callback_query.message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cb_tracked_subs_with_subs(
    mock_db, mock_bot, mock_callback_query, mock_app_state
):
    mock_callback_query.data = "tracked_subs:1"
    user = User(id=123456789, chat_id=123456789)
    sub = Subscription(id=1, frequency="daily")
    mock_db.get = AsyncMock(return_value=user)
    mock_db.execute.return_value.scalars.return_value.all.return_value = [sub]

    await cb_tracked_subs(mock_callback_query)

    # reply_markup передаётся как именованный аргумент
    reply_markup = mock_callback_query.message.answer.call_args.kwargs["reply_markup"]
    assert "Удалить daily" in reply_markup.inline_keyboard[0][0].text


@pytest.mark.asyncio
async def test_cb_sub_remove(mock_db, mock_bot, mock_callback_query, mock_app_state):
    mock_callback_query.data = "sub_remove:1"
    sub = Subscription(id=1)
    mock_db.get = AsyncMock(return_value=sub)
    await cb_sub_remove(mock_callback_query)
    mock_db.delete.assert_called_once_with(sub)
    mock_db.commit.assert_called_once()
    mock_callback_query.message.answer.assert_called_once()
    mock_app_state["cleanup_manager"].replace_message.assert_called_once()


@pytest.mark.asyncio
async def test_cb_tracked_alerts_no_alerts(
    mock_db, mock_bot, mock_callback_query, mock_app_state
):
    mock_callback_query.data = "tracked_alerts:1"
    user = User(id=123456789, chat_id=123456789)
    mock_db.get = AsyncMock(return_value=user)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    await cb_tracked_alerts(mock_callback_query)
    assert "Ваши алерты" in mock_callback_query.message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cb_alert_remove(mock_db, mock_bot, mock_callback_query, mock_app_state):
    mock_callback_query.data = "alert_remove:1"
    alert = PriceAlert(id=1)
    mock_db.get = AsyncMock(return_value=alert)
    await cb_alert_remove(mock_callback_query)
    mock_db.delete.assert_called_once_with(alert)
    mock_db.commit.assert_called_once()
    mock_callback_query.message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cb_alert_add_start(
    mock_db, mock_bot, mock_callback_query, mock_state, mock_app_state
):
    mock_callback_query.data = "alert_add_start:1"
    await cb_alert_add_start(mock_callback_query, mock_state)
    mock_state.update_data.assert_called_once_with(item_id=1)
    mock_state.set_state.assert_called_once()
    mock_callback_query.message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_process_alert_percent_invalid(
    mock_db, mock_bot, mock_message, mock_state, mock_app_state
):
    mock_message.text = "abc"
    await process_alert_percent(mock_message, mock_state)
    assert "Неверный процент" in mock_message.answer.call_args[0][0]
    mock_state.update_data.assert_not_called()


@pytest.mark.asyncio
async def test_process_alert_percent_valid(
    mock_db, mock_bot, mock_message, mock_state, mock_app_state
):
    mock_message.text = "10"
    await process_alert_percent(mock_message, mock_state)
    mock_state.update_data.assert_called_once_with(percent=10.0)
    mock_state.set_state.assert_called_once()
    mock_message.delete.assert_called_once()
    mock_message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cb_alert_period(
    mock_db, mock_bot, mock_callback_query, mock_state, mock_app_state
):
    mock_callback_query.data = "alert_period:24h"
    mock_state.get_data = AsyncMock(return_value={"item_id": 1, "percent": 10.0})
    user = User(id=123456789, chat_id=123456789)
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.get = AsyncMock(
        side_effect=lambda model, pk: user if model == User else item
    )
    await cb_alert_period(mock_callback_query, mock_state)
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_state.clear.assert_called_once()
    mock_callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_cb_tracked_untrack(
    mock_db, mock_bot, mock_callback_query, mock_app_state
):
    mock_callback_query.data = "tracked_untrack:1"
    user = User(id=123456789, chat_id=123456789)
    tracked = UserTrackedItem(user_id=123456789, item_id=1)
    mock_db.get = AsyncMock(
        side_effect=lambda model, pk: user if model == User else tracked
    )
    await cb_tracked_untrack(mock_callback_query)
    mock_db.delete.assert_called_once_with(tracked)
    assert mock_db.execute.call_count >= 2  # два delete запроса
    mock_db.commit.assert_called_once()
    mock_callback_query.message.answer.assert_called_once()


# -----------------------------------------------------------------------------
# Тесты для команд-заглушек
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_subscribe(mock_db, mock_bot, mock_message, mock_app_state):
    with patch(
        "app.bot.dispatcher.reply_use_help", new_callable=AsyncMock
    ) as mock_reply:
        await cmd_subscribe(mock_message)
    mock_reply.assert_called_once_with(mock_message)


@pytest.mark.asyncio
async def test_cmd_alert(mock_db, mock_bot, mock_message, mock_state, mock_app_state):
    with patch(
        "app.bot.dispatcher.reply_use_help", new_callable=AsyncMock
    ) as mock_reply:
        await cmd_alert(mock_message, mock_state)
    mock_reply.assert_called_once_with(mock_message)


@pytest.mark.asyncio
async def test_cmd_untrack(mock_db, mock_bot, mock_message, mock_app_state):
    with patch(
        "app.bot.dispatcher.reply_use_help", new_callable=AsyncMock
    ) as mock_reply:
        await cmd_untrack(mock_message)
    mock_reply.assert_called_once_with(mock_message)


@pytest.mark.asyncio
async def test_cmd_unsubscribe(mock_db, mock_bot, mock_message, mock_app_state):
    with patch(
        "app.bot.dispatcher.reply_use_help", new_callable=AsyncMock
    ) as mock_reply:
        await cmd_unsubscribe(mock_message)
    mock_reply.assert_called_once_with(mock_message)


@pytest.mark.asyncio
async def test_cmd_delete_alert(mock_db, mock_bot, mock_message, mock_app_state):
    with patch(
        "app.bot.dispatcher.reply_use_help", new_callable=AsyncMock
    ) as mock_reply:
        await cmd_delete_alert(mock_message)
    mock_reply.assert_called_once_with(mock_message)


# -----------------------------------------------------------------------------
# Тесты для send_price_chart
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_price_chart_from_cache(mock_db, mock_bot, mock_app_state):
    mock_app_state["redis_client"].get = AsyncMock(return_value=b"png_bytes")
    mock_bot.send_photo = AsyncMock()

    # Обязательно возвращаем предмет, чтобы код дошёл до Redis
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.get = AsyncMock(return_value=item)

    with patch("app.bot.dispatcher.bot", mock_bot):
        await send_price_chart(chat_id=123456789, item_id=1, days=30)

    mock_app_state["redis_client"].get.assert_called_once()
    mock_bot.send_photo.assert_called_once()


@pytest.mark.asyncio
async def test_send_price_chart_generates_new(mock_db, mock_bot, mock_app_state):
    mock_app_state["redis_client"].get = AsyncMock(return_value=None)
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.get = AsyncMock(return_value=item)

    # Для days=30 используется ItemHourlyStats
    stat = ItemHourlyStats(
        item_id=1,
        timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
        price=10.0,
        volume=100,
    )
    mock_db.execute.return_value.scalars.return_value.all.return_value = [stat]

    with (
        patch("app.bot.dispatcher.generate_price_chart", return_value=b"chart"),
        patch("app.bot.dispatcher.bot", mock_bot),
    ):
        mock_bot.send_photo = AsyncMock()
        await send_price_chart(chat_id=123456789, item_id=1, days=30)

    mock_app_state["redis_client"].setex.assert_called_once()
    mock_bot.send_photo.assert_called_once()


@pytest.mark.asyncio
async def test_send_price_chart_hourly(mock_db, mock_bot, mock_app_state):
    mock_app_state["redis_client"].get = AsyncMock(return_value=None)
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.get = AsyncMock(return_value=item)
    hourly = [
        ItemHourlyStats(
            item_id=1,
            timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
            price=10.0,
            volume=100,
        ),
        ItemHourlyStats(
            item_id=1,
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
            price=11.0,
            volume=120,
        ),
    ]
    mock_db.execute.return_value.scalars.return_value.all.return_value = hourly
    with (
        patch("app.bot.dispatcher.generate_price_chart", return_value=b"chart"),
        patch("app.bot.dispatcher.bot", mock_bot),
    ):
        mock_bot.send_photo = AsyncMock()
        await send_price_chart(chat_id=123456789, item_id=1, days=7)
    mock_app_state["redis_client"].setex.assert_called_once()
    mock_bot.send_photo.assert_called_once()


@pytest.mark.asyncio
async def test_send_price_chart_daily_all_time(mock_db, mock_bot, mock_app_state):
    mock_app_state["redis_client"].get = AsyncMock(return_value=None)
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.get = AsyncMock(return_value=item)
    daily = [
        ItemDailyStats(
            item_id=1,
            date=datetime.now(timezone.utc).date() - timedelta(days=2),
            price=10.0,
            volume=100,
        ),
        ItemDailyStats(
            item_id=1,
            date=datetime.now(timezone.utc).date() - timedelta(days=1),
            price=11.0,
            volume=120,
        ),
    ]
    mock_db.execute.return_value.scalars.return_value.all.return_value = daily
    with (
        patch("app.bot.dispatcher.generate_price_chart", return_value=b"chart"),
        patch("app.bot.dispatcher.bot", mock_bot),
    ):
        mock_bot.send_photo = AsyncMock()
        await send_price_chart(chat_id=123456789, item_id=1, days=None)  # all time
    mock_app_state["redis_client"].setex.assert_called_once()
    mock_bot.send_photo.assert_called_once()


@pytest.mark.asyncio
async def test_send_price_chart_no_records(mock_db, mock_bot, mock_app_state):
    mock_app_state["redis_client"].get = AsyncMock(return_value=None)
    item = Item(id=1, app_id=730, market_hash_name="AK-47")
    mock_db.get = AsyncMock(return_value=item)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    with (
        patch("app.bot.dispatcher.generate_price_chart") as mock_gen,
        patch("app.bot.dispatcher.bot", mock_bot),
    ):
        mock_bot.send_photo = AsyncMock()
        await send_price_chart(chat_id=123456789, item_id=1, days=7)
    mock_bot.send_photo.assert_not_called()
    mock_gen.assert_not_called()
