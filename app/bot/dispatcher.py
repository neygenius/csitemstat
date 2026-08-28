import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.config import settings
from app.db.base import async_session
from app.db.models import User, Item, UserTrackedItem, Subscription, PriceAlert, ItemDailyStats, ItemSnapshot
from app.services.steam_client import SteamClient
from app.services.inventory import fetch_grouped_inventory, group_inventory
from app.services.statistics import compute_trend, percent_change
from app.services.plotter import generate_price_chart
from app.bot.messages import send_telegram_message, send_photo
from app.services.crypto import encrypt_steam_id, decrypt_steam_id
from app.bot.keyboards import inventory_pagination, item_actions, subscription_choice, portfolio_pagination, tracked_item_actions, alert_period_keyboard
from sqlalchemy import select, func
from datetime import date, timedelta, datetime, timezone
import redis.asyncio as redis
import json

logger = logging.getLogger(__name__)

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

# Состояния для FSM
class LinkSteam(StatesGroup):
    waiting_for_steam_id = State()

class AlertForm(StatesGroup):
    waiting_for_percent = State()
    waiting_for_period = State()

# Redis клиент инициализируется в lifespan
redis_client = None

# Вспомогательная функция получения сессии
async def get_db():
    async with async_session() as session:
        yield session


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    async for session in get_db():
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(id=message.from_user.id, chat_id=message.chat.id)
            session.add(user)
            await session.commit()

        await message.answer(
            "👋 Добро пожаловать в трекер цен Steam!\n"
            "Добавляйте предметы в портфель, следите за ценами, подписывайтесь на уведомления\n\n"
            "Основные команды:\n"
            "/link_steam - привязать Steam ID\n"
            "/inventory - ваш инвентарь Steam\n"
            "/bagpack - управление отслеживаемыми предметами\n"
            "/help - помощь"
        )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📋 Справка по командам:\n\n"
        "/start - регистрация\n"
        "/link_steam - привязать Steam ID\n"
        "/inventory - ваш инвентарь Steam\n"
        "/bagpack – ваш портфель отслеживаемых предметов\n"
        "/track <название> - начать отслеживание предмета\n"
        "/stats <название> - статистика и график цены\n"
        "/help - эта справка\n\n"
        "Все действия с подписками, алертами и удалением выполняются через портфель"
    )
    await message.answer(text)


@dp.message(Command("link_steam"))
async def cmd_link_steam(message: types.Message, state: FSMContext):
    await state.set_state(LinkSteam.waiting_for_steam_id)
    await message.answer("Введите ваш SteamID64 (полный ID профиля)")

@dp.message(LinkSteam.waiting_for_steam_id)
async def process_steam_id(message: types.Message, state: FSMContext):
    try:
        steam_id = int(message.text.strip())
    except ValueError:
        await message.answer("Неверный формат: SteamID64 должен быть числом. Попробуйте ещё раз")
        return
    
    async for session in get_db():
        user = await session.get(User, message.from_user.id)
        if user:
            user.steam_id64 = encrypt_steam_id(steam_id)
            await session.commit()
        await state.clear()
        await message.answer("✅ Steam ID успешно привязан!")


@dp.message(Command("inventory"))
async def cmd_inventory(message: types.Message):
    async for session in get_db():
        user = await session.get(User, message.from_user.id)
        if not user or not user.steam_id64:
            await message.answer("Сначала привяжите Steam ID командой /link_steam")
            return
        steam_id = decrypt_steam_id(user.steam_id64)

    # Если есть в кэше
    cache_key = f"inv:{message.from_user.id}"
    if redis_client:
        cached = await redis_client.get(cache_key)
        if cached:
            items_list = json.loads(cached)
            total_pages = (len(items_list) + 9) // 10
            await message.answer(
                f"🎒 Ваш инвентарь (страница 1/{total_pages}):",
                reply_markup=inventory_pagination(items_list, page=0)
            )
            return

    # Если нет в кэше
    steam_client = SteamClient()
    try:
        raw = await fetch_grouped_inventory(steam_client, steam_id, settings.APP_ID)
    except Exception as e:
        logger.error(f"Inventory fetch error: {e}")
        await message.answer("Не удалось загрузить инвентарь. Попробуйте позже")
        await steam_client.close()
        return
    await steam_client.close()

    if not raw:
        await message.answer("Инвентарь пуст или скрыт")
        return
    
    items_list = []
    for name, cnt in sorted(raw.items()):
        items_list.append((name, cnt))

    # Кэшируем на 5 минут
    if redis_client:
        await redis_client.setex(cache_key, 300, json.dumps(items_list))

    total_pages = (len(items_list) + 9) // 10
    await message.answer(
        f"🎒 Ваш инвентарь (страница 1/{total_pages}):",
        reply_markup=inventory_pagination(items_list, page=0)
    )


@dp.callback_query(F.data.startswith("inv_page:"))
async def cb_inventory_page(callback: types.CallbackQuery):
    page = int(callback.data.split(":")[1])
    cache_key = f"inv:{callback.from_user.id}"
    if not redis_client:
        await callback.answer("Кэш недоступен")
        return
    cached = await redis_client.get(cache_key)

    if not cached:
        await callback.answer("Инвентарь устарел, запросите заново /inventory")
        return
    
    items_list = json.loads(cached)
    total_pages = (len(items_list) + 9) // 10
    await callback.message.edit_text(
        f"🎒 Ваш инвентарь (страница {page+1}/{total_pages}):",
        reply_markup=inventory_pagination(items_list, page)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("add_track:"))
async def cb_add_track(callback: types.CallbackQuery):
    market_hash_name = callback.data.split(":", 1)[1]
    async for session in get_db():
        stmt = select(Item).where(
            Item.market_hash_name == market_hash_name,
            Item.app_id == settings.APP_ID
        )
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()

        # Проверяем, если предмета еще нет - создаем
        if not item:
            item = Item(app_id=settings.APP_ID, market_hash_name=market_hash_name)
            session.add(item)
            await session.flush()

        user = await session.get(User, callback.from_user.id)
        if not user:
            user = User(id=callback.from_user.id, chat_id=callback.message.chat.id)
            session.add(user)
        
        existing = await session.get(UserTrackedItem, (user.id, item.id))
        if existing:
            await callback.answer("Этот предмет уже в вашем портфеле")
            return

        session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
        await session.commit()
        await callback.answer(f"✅ Предмет '{item.market_hash_name}' добавлен в портфель!")
        await callback.message.edit_reply_markup(reply_markup=None)


@dp.message(Command("track"))
async def cmd_track(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /track <название предмета>")
        return
    
    name = args[1].strip()
    async for session in get_db():
        stmt = select(Item).where(
            Item.market_hash_name.ilike(f"%{name}%"),
            Item.app_id == settings.APP_ID).limit(8)
        result = await session.execute(stmt)
        items = result.scalars().all()

        if not items:
            await message.answer("Предмет не найден. Проверьте название")
            return
        
        if len(items) > 1:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{it.market_hash_name}",
                                      callback_data=f"add_track:{it.market_hash_name}")] for it in items[:8]
            ])
            await message.answer("Найдено несколько предметов, выберите интересующий:", reply_markup=kb)
            return 
        
        item = items[0]
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(id=message.from_user.id, chat_id=message.chat.id)
            session.add(user)
        
        existing = await session.get(UserTrackedItem, (user.id, item.id))
        if existing:
            await message.answer("Этот предмет уже в вашем портфеле")
            return
        
        session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
        await session.commit()
        await message.answer(f"✅ Предмет '{item.market_hash_name}' добавлен в портфель!", reply_markup=item_actions(item.id))


@dp.message(Command("bagpack"))
async def cmd_portfolio(message: types.Message):
    items_per_page = 10
    page = 0

    async for session in get_db():
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала выполните /start")
            return

        stmt = select(Item).join(UserTrackedItem).where(UserTrackedItem.user_id == user.id)
        result = await session.execute(stmt)
        items = result.scalars().all()

        if not items:
            await message.answer("Ваш портфель пуст. Добавьте предметы через /track или /inventory")
            return

        total_pages = (len(items) + items_per_page - 1) // items_per_page
        text = f"📁 Ваш портфель (страница {page + 1}/{total_pages}):"
        keyboard = portfolio_pagination(items, page, items_per_page)

        await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("portfolio_page:"))
async def cb_portfolio_page(callback: types.CallbackQuery):
    page = int(callback.data.split(":")[1])
    items_per_page = 10

    async for session in get_db():
        stmt = select(Item).join(UserTrackedItem).where(UserTrackedItem.user_id == callback.from_user.id)
        result = await session.execute(stmt)
        items = result.scalars().all()

        if not items:
            await callback.message.edit_text("Произошла ошибка")
            await callback.answer()
            return

        total_pages = (len(items) + items_per_page - 1) // items_per_page
        if page < 0 or page >= total_pages:
            page = 0

        text = f"📁 Ваш портфель (страница {page + 1}/{total_pages}):"
        keyboard = portfolio_pagination(items, page, items_per_page)

        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@dp.callback_query(F.data.startswith("tracked_item:"))
async def cb_tracked_item(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    keyboard = tracked_item_actions(item_id)
    await callback.message.answer("Выберите действие:", reply_markup=keyboard)
    await callback.answer()


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /stats <название предмета>")
        return
    
    name = args[1].strip()
    async for session in get_db():
        stmt = select(Item).where(Item.market_hash_name.ilike(f"%{name}%"),
                                  Item.app_id == settings.APP_ID).limit(8)
        result = await session.execute(stmt)
        items = result.scalars().all()

        if not items:
            await message.answer("Предмет не найден")
            return

        if len(items) > 1:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{it.market_hash_name}",
                                      callback_data=f"stats:{it.id}")] for it in items[:8]
            ])
            await message.answer("Найдено несколько предметов, выберите интересующий:", reply_markup=kb)
            return 
        
        item = items[0]
        snapshot = await session.get(ItemSnapshot, item.id)
        if not snapshot:
            await message.answer("Нет данных. Попробуйте позже")
            return
        
        # Базовое summary
        trend = snapshot.trend_direction or "—"
        text = (
            f"📊 {item.market_hash_name}\n"
            f"Мин. цена: {float(snapshot.lowest_price):.2f} {settings.CURRENCY_SYMBOL}\n"
            f"Медиана: {float(snapshot.median_price):.2f} {settings.CURRENCY_SYMBOL}\n"
            f"Объём (24ч): {snapshot.volume_24h}\n"
            f"Тренд (7д): {trend}"
        )

        if snapshot.price_24h_ago:
            change = percent_change(float(snapshot.median_price), float(snapshot.price_24h_ago))
            text += f"\nИзменения за сутки: {'↑' if change>0 else '↓' if change<0 else '→'} {abs(change):.1f}%"
        await message.answer(text, reply_markup=item_actions(item.id))

        # Отправляем график (если есть история)
        stmt_hist = select(ItemDailyStats).where(ItemDailyStats.item_id == item.id).order_by(ItemDailyStats.date.asc()).limit(90)
        hist_res = await session.execute(stmt_hist)
        records = hist_res.scalars().all()
        if records:
            dates = [datetime.combine(r.date, datetime.min.time()) for r in records]
            prices = [float(r.price) for r in records]
            img_bytes = generate_price_chart(dates, prices, item.market_hash_name)
            await send_photo(settings.BOT_TOKEN, message.chat.id, img_bytes)


# переиспользование логики команды /stats с точным названием предмета
@dp.callback_query(F.data.startswith("stats:"))
async def cb_stats(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    async for session in get_db():
        item = await session.get(Item, item_id)
        if item:
            await cmd_stats(callback.message, item.market_hash_name)
    await callback.answer()


@dp.callback_query(F.data.startswith("sub_add:"))
async def cb_sub_add(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Неверные данные")
        return
    
    item_id = int(parts[1])
    freq = parts[2]
    async for session in get_db():
        user = await session.get(User, callback.from_user.id)
        if not user:
            await callback.answer("Сначала используйте /start")
            return

        item = await session.get(Item, item_id)
        if not item:
            await callback.answer("Предмет не найден. Добавьте его в ваш портфель")
            return

        existing = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.item_id == item.id,
                Subscription.frequency == freq
            )
        )

        sub = existing.scalar_one_or_none()
        if sub:
            sub.active = True
            await session.commit()
            await callback.answer(f"Подписка на '{item.market_hash_name}' ({freq}) уже активна")

        session.add(Subscription(user_id=user.id, item_id=item.id, frequency=freq))
        await session.commit()
        await callback.answer(f"✅ Подписка на '{item.market_hash_name}' ({freq}) активирована!")
        await callback.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("subs:"))
async def cb_subs(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    await callback.message.answer("Выберите период:", reply_markup=subscription_choice(item_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("tracked_subs:"))
async def cb_tracked_subs(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])

    async for session in get_db():
        user = await session.get(User, callback.from_user.id)
        if not user:
            await callback.answer("Сначала выполните /start")
            return

        subs = (await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.item_id == item_id,
                Subscription.active == True
            )
        )).scalars().all()

        text = "🔔 Ваши подписки на этот предмет:\n"
        kb_buttons = []
        for sub in subs:
            text += f"• {sub.frequency}\n"
            kb_buttons.append([
                InlineKeyboardButton(text=f"⚠️ Удалить {sub.frequency} ", callback_data=f"sub_remove:{sub.id}")
            ])

        existing_periods = {sub.frequency for sub in subs}
        if "daily" not in existing_periods:
            kb_buttons.append([InlineKeyboardButton(text="➕ Добавить daily",
                                                    callback_data=f"sub_add:{item_id}:daily")])
        if "weekly" not in existing_periods:
            kb_buttons.append([InlineKeyboardButton(text="➕ Добавить weekly",
                                                    callback_data=f"sub_add:{item_id}:weekly")])

        if not kb_buttons:
            text += "Нет активных подписок, но можно добавить"
            kb_buttons = [
                [InlineKeyboardButton(text="➕ Добавить daily",
                                      callback_data=f"sub_add:{item_id}:daily")],
                [InlineKeyboardButton(text="➕ Добавить weekly",
                                      callback_data=f"sub_add:{item_id}:weekly")]
            ]

        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))
        await callback.answer()


@dp.callback_query(F.data.startswith("sub_remove:"))
async def cb_sub_remove(callback: types.CallbackQuery):
    sub_id = int(callback.data.split(":")[1])
    async for session in get_db():
        sub = await session.get(Subscription, sub_id)
        if sub:
            await session.delete(sub)
            await session.commit()
            await callback.answer("Подписка удалена")
        else:
            await callback.answer("Подписка не найдена")


@dp.callback_query(F.data.startswith("tracked_alerts:"))
async def cb_tracked_alerts(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])

    async for session in get_db():
        user = await session.get(User, callback.from_user.id)
        if not user:
            await callback.answer("Сначала выполните /start")
            return

        alerts = (await session.execute(
            select(PriceAlert).where(
                PriceAlert.user_id == user.id,
                PriceAlert.item_id == item_id,
                PriceAlert.active == True
            )
        )).scalars().all()

        text = "⏰ Ваши алерты на этот предмет:\n"
        kb_buttons = []
        for alert in alerts:
            text += f"• {alert.percent_change}% за {alert.period}\n"
            kb_buttons.append([
                InlineKeyboardButton(text=f"⚠️ Удалить {alert.percent_change}% алерт", callback_data=f"alert_remove:{alert.id}")
            ])

        kb_buttons.append([
            InlineKeyboardButton(text="➕ Добавить алерт", callback_data=f"alert_add_start:{item_id}")
        ])

        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))
        await callback.answer()


@dp.callback_query(F.data.startswith("alert_remove:"))
async def cb_alert_remove(callback: types.CallbackQuery):
    alert_id = int(callback.data.split(":")[1])
    async for session in get_db():
        alert = await session.get(PriceAlert, alert_id)
        if alert:
            await session.delete(alert)
            await session.commit()
            await callback.answer("Алерт удален")
        else:
            await callback.answer("Алерт не найден")


@dp.callback_query(F.data.startswith("alert_add_start:"))
async def cb_alert_add_start(callback: types.CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split(":")[1])
    await state.update_data(item_id=item_id)
    await state.set_state(AlertForm.waiting_for_percent)
    await callback.message.answer("Введите процент изменения цены (например, 10):")
    await callback.answer()


@dp.message(AlertForm.waiting_for_percent)
async def process_alert_percent(message: types.Message, state: FSMContext):
    try:
        percent = float(message.text.strip().replace('%', ''))
        if percent <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Неверный процент. Введите положительное число.")
        return

    await state.update_data(percent=percent)
    await state.set_state(AlertForm.waiting_for_period)
    await message.answer("Выберите период:", reply_markup=alert_period_keyboard())


@dp.callback_query(F.data.startswith("alert_period:"))
async def cb_alert_period(callback: types.CallbackQuery, state: FSMContext):
    period = callback.data.split(":")[1]
    data = await state.get_data()
    item_id = data.get("item_id")
    percent = data.get("percent")

    if not item_id or not percent:
        await callback.answer("Ошибка: данные утеряны")
        await state.clear()
        return

    async for session in get_db():
        user = await session.get(User, callback.from_user.id)
        if not user:
            await callback.answer("Сначала выполните /start")
            await state.clear()
            return

        item = await session.get(Item, item_id)
        if not item:
            await callback.answer("Предмет не найден")
            await state.clear()
            return

        session.add(PriceAlert(
            user_id=user.id,
            item_id=item.id,
            percent_change=percent,
            period=period,
            active=True
        ))
        await session.commit()

        await callback.message.answer(f"✅ Алерт создан: {percent}% за {period} для '{item.market_hash_name}'")
        await state.clear()
        await callback.answer()


@dp.callback_query(F.data.startswith("tracked_untrack:"))
async def cb_tracked_untrack(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])

    async for session in get_db():
        user = await session.get(User, callback.from_user.id)
        if not user:
            await callback.answer("Сначала выполните /start")
            return

        tracked = await session.get(UserTrackedItem, (user.id, item_id))
        if not tracked:
            await callback.answer("Этот предмет не отслеживается")
            return

        await session.delete(tracked)
        await session.commit()
        await callback.answer("Предмет удалён из портфеля")
        await callback.message.edit_reply_markup(reply_markup=None)


async def reply_use_help(message: types.Message):
    await message.answer(
        "Данная команда в данный момент не поддерживается\n"
        "Пожалуйста, откройте /bagpack для управления предметами, подписками и алертами, "
        "или ознакомьтесь с /help"
    )


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: types.Message):
    await reply_use_help(message)


@dp.message(Command("alert"))
async def cmd_alert(message: types.Message, state: FSMContext):
    await reply_use_help(message)


@dp.message(Command("untrack"))
async def cmd_untrack(message: types.Message):
    await reply_use_help(message)


@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    await reply_use_help(message)


@dp.message(Command("delete_alert"))
async def cmd_delete_alert(message: types.Message):
    await reply_use_help(message)
