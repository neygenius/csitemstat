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
from app.bot.keyboards import inventory_pagination, item_actions, subscription_choice
from sqlalchemy import select, func
from datetime import date, timedelta, datetime, timezone
import redis.asyncio as redis

logger = logging.getLogger(__name__)

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

# Состояния для FSM
class LinkSteam(StatesGroup):
    waiting_for_steam_id = State()

class AlertForm(StatesGroup):
    waiting_for_percent = State()
    waiting_for_period = State()

# Общий Redis клиент (инициализируется в lifespan)
redis_client = None

# Вспомогательная функция получения сессии
async def get_db():
    async with async_session() as session:
        yield session

# --------------------- Команда /start ---------------------
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
            "Используйте команды:\n"
            "/inventory - ваш инвентарь\n"
            "/link_steam - привязать Steam ID\n"
            "/track <название> - отслеживать предмет\n"
            "/stats <название> - статистика\n"
            "/subscribe <название> daily|weekly - подписка\n"
            "/alert <название> - создать алерт\n"
            "/help - помощь"
        )

# --------------------- /link_steam ---------------------
@dp.message(Command("link_steam"))
async def cmd_link_steam(message: types.Message, state: FSMContext):
    await state.set_state(LinkSteam.waiting_for_steam_id)
    await message.answer("Введите ваш Steam ID64 (числовой ID профиля):")

@dp.message(LinkSteam.waiting_for_steam_id)
async def process_steam_id(message: types.Message, state: FSMContext):
    try:
        steam_id = int(message.text.strip())
    except ValueError:
        await message.answer("Неверный формат. Steam ID64 должен быть числом. Попробуйте ещё раз.")
        return
    async for session in get_db():
        user = await session.get(User, message.from_user.id)
        if user:
            user.steam_id64 = encrypt_steam_id(steam_id)
            await session.commit()
        await state.clear()
        await message.answer("✅ Steam ID успешно привязан!")

# --------------------- /inventory ---------------------
@dp.message(Command("inventory"))
async def cmd_inventory(message: types.Message):
    async for session in get_db():
        user = await session.get(User, message.from_user.id)
        if not user or not user.steam_id64:
            await message.answer("Сначала привяжите Steam ID командой /link_steam")
            return
        steam_id = decrypt_steam_id(user.steam_id64)
    # Пробуем получить из кэша
    cache_key = f"inv:{message.from_user.id}"
    if redis_client:
        cached = await redis_client.get(cache_key)
        if cached:
            items_list = eval(cached)  # проще хранить как repr(list) или json
            total_pages = (len(items_list) + 9) // 10
            await message.answer(
                f"🎒 Ваш инвентарь (страница 1/{total_pages}):",
                reply_markup=inventory_pagination(items_list, page=0)
            )
            return
    # Если нет в кэше, загружаем
    steam_client = SteamClient()
    try:
        raw = await fetch_grouped_inventory(steam_client, steam_id, settings.APP_ID)
    except Exception as e:
        logger.error(f"Inventory fetch error: {e}")
        await message.answer("Не удалось загрузить инвентарь. Попробуйте позже.")
        await steam_client.close()
        return
    await steam_client.close()
    if not raw:
        await message.answer("Инвентарь пуст или скрыт.")
        return
    items_list = []
    for name, cnt in sorted(raw.items()):
        # Получаем или создаем item в БД
        async for session in get_db():
            stmt = select(Item).where(Item.market_hash_name == name, Item.app_id == settings.APP_ID)
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()
            if not item:
                item = Item(app_id=settings.APP_ID, market_hash_name=name, name=name)
                session.add(item)
                await session.flush()
            items_list.append((item.id, name, cnt))
    # Кэшируем на 5 минут
    if redis_client:
        await redis_client.setex(cache_key, 300, repr(items_list))
    total_pages = (len(items_list) + 9) // 10
    await message.answer(
        f"🎒 Ваш инвентарь (страница 1/{total_pages}):",
        reply_markup=inventory_pagination(items_list, page=0)
    )

# --------------------- Callback: пагинация инвентаря ---------------------
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
    items_list = eval(cached)
    total_pages = (len(items_list) + 9) // 10
    await callback.message.edit_text(
        f"🎒 Ваш инвентарь (страница {page+1}/{total_pages}):",
        reply_markup=inventory_pagination(items_list, page)
    )
    await callback.answer()

# --------------------- Callback: добавить предмет в отслеживание ---------------------
@dp.callback_query(F.data.startswith("add_track:"))
async def cb_add_track(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    async for session in get_db():
        # Проверяем существование предмета и пользователя
        user = await session.get(User, callback.from_user.id)
        item = await session.get(Item, item_id)
        if not user or not item:
            await callback.answer("Ошибка")
            return
        # Добавляем в отслеживание
        existing = await session.get(UserTrackedItem, (user.id, item_id))
        if not existing:
            session.add(UserTrackedItem(user_id=user.id, item_id=item_id))
            await session.commit()
            await callback.answer("Предмет добавлен в отслеживание!")
        else:
            await callback.answer("Уже отслеживается")
    await callback.message.edit_reply_markup(reply_markup=None)

# --------------------- /track ---------------------
@dp.message(Command("track"))
async def cmd_track(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /track <название предмета>")
        return
    name = args[1].strip()
    async for session in get_db():
        stmt = select(Item).where(Item.market_hash_name.ilike(f"%{name}%"), Item.app_id == settings.APP_ID)
        result = await session.execute(stmt)
        items = result.scalars().all()
        if not items:
            await message.answer("Предмет не найден. Проверьте название.")
            return
        if len(items) > 1:
            # Предлагаем выбор
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{it.market_hash_name}", callback_data=f"add_track:{it.id}")] for it in items[:5]
            ])
            await message.answer("Найдено несколько, выберите:", reply_markup=kb)
            return
        item = items[0]
        # Добавляем
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(id=message.from_user.id, chat_id=message.chat.id)
            session.add(user)
        existing = await session.get(UserTrackedItem, (user.id, item.id))
        if existing:
            await message.answer("Этот предмет уже в списке отслеживания.")
            return
        session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
        await session.commit()
        await message.answer(f"Предмет '{item.market_hash_name}' добавлен в отслеживание.", reply_markup=item_actions(item.id))

# --------------------- /stats ---------------------
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /stats <название предмета>")
        return
    name = args[1].strip()
    async for session in get_db():
        stmt = select(Item).where(Item.market_hash_name.ilike(f"%{name}%"), Item.app_id == settings.APP_ID)
        result = await session.execute(stmt)
        items = result.scalars().all()
        if not items:
            await message.answer("Предмет не найден.")
            return
        # Берем первый подходящий (или можно дать выбор)
        item = items[0]
        snapshot = await session.get(ItemSnapshot, item.id)
        if not snapshot:
            await message.answer("Нет данных. Попробуйте позже.")
            return
        # Базовое summary
        trend = snapshot.trend_direction or "—"
        text = (
            f"📊 <b>{item.market_hash_name}</b>\n"
            f"Мин. цена: ${float(snapshot.lowest_price):.2f}\n"
            f"Медиана: ${float(snapshot.median_price):.2f}\n"
            f"Объём (24ч): {snapshot.volume_24h}\n"
            f"Тренд (7д): {trend}"
        )
        if snapshot.price_24h_ago:
            change = percent_change(float(snapshot.median_price), float(snapshot.price_24h_ago))
            text += f"\nИзм. за сутки: {'↑' if change>0 else '↓' if change<0 else '→'} {abs(change):.1f}%"
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

# --------------------- /subscribe ---------------------
@dp.message(Command("subscribe"))
async def cmd_subscribe(message: types.Message):
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Использование: /subscribe <название> daily|weekly")
        return
    period = args[-1].lower()
    if period not in ('daily', 'weekly'):
        await message.answer("Период должен быть daily или weekly")
        return
    name = " ".join(args[1:-1])
    async for session in get_db():
        stmt = select(Item).where(Item.market_hash_name.ilike(f"%{name}%"), Item.app_id == settings.APP_ID)
        result = await session.execute(stmt)
        items = result.scalars().all()
        if not items:
            await message.answer("Предмет не найден.")
            return
        item = items[0]
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(id=message.from_user.id, chat_id=message.chat.id)
            session.add(user)
            await session.flush()
        existing = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.item_id == item.id,
                Subscription.frequency == period
            )
        )
        existing_sub = existing.scalar_one_or_none()
        if existing_sub:
            existing_sub.active = True
            await session.commit()
            await message.answer(f"Подписка на {period} обновления для '{item.market_hash_name}' активирована.")
        else:
            session.add(Subscription(user_id=user.id, item_id=item.id, frequency=period))
            await session.commit()
            await message.answer(f"Вы подписались на {period} уведомления о '{item.market_hash_name}'.")

# --------------------- /alert ---------------------
@dp.message(Command("alert"))
async def cmd_alert(message: types.Message, state: FSMContext):
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Использование: /alert <название> <процент> [24h|7d]")
        return
    try:
        percent = float(args[-1].replace('%', ''))
    except ValueError:
        await message.answer("Процент должен быть числом.")
        return
    period = "24h"
    if len(args) > 2 and args[-2] in ('24h', '7d'):
        period = args[-2]
        name = " ".join(args[1:-2])
    else:
        name = " ".join(args[1:-1])
    async for session in get_db():
        stmt = select(Item).where(Item.market_hash_name.ilike(f"%{name}%"), Item.app_id == settings.APP_ID)
        result = await session.execute(stmt)
        items = result.scalars().all()
        if not items:
            await message.answer("Предмет не найден.")
            return
        item = items[0]
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(id=message.from_user.id, chat_id=message.chat.id)
            session.add(user)
            await session.flush()
        session.add(PriceAlert(
            user_id=user.id,
            item_id=item.id,
            percent_change=percent,
            period=period,
            active=True
        ))
        await session.commit()
        await message.answer(f"Алерт создан: изменение цены '{item.market_hash_name}' на {percent}% за {period}.")

# --------------------- /alerts ---------------------
@dp.message(Command("alerts"))
async def cmd_list_alerts(message: types.Message):
    async for session in get_db():
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала выполните /start")
            return
        alerts = (await session.execute(
            select(PriceAlert).where(PriceAlert.user_id == user.id, PriceAlert.active == True)
        )).scalars().all()
        if not alerts:
            await message.answer("У вас нет активных алертов.")
            return
        text = "🔔 Ваши алерты:\n"
        for a in alerts:
            item = await session.get(Item, a.item_id)
            text += f"• {item.market_hash_name}: {a.percent_change}% за {a.period} (ID {a.id})\n"
        await message.answer(text)

# --------------------- /untrack ---------------------
@dp.message(Command("untrack"))
async def cmd_untrack(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /untrack <название предмета>")
        return
    name = args[1].strip()
    async for session in get_db():
        stmt = select(Item).where(Item.market_hash_name.ilike(f"%{name}%"), Item.app_id == settings.APP_ID)
        result = await session.execute(stmt)
        items = result.scalars().all()
        if not items:
            await message.answer("Предмет не найден.")
            return
        # если найдено несколько – берем первый или предлагаем выбор (упростим)
        item = items[0]
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала выполните /start")
            return
        tracked = await session.get(UserTrackedItem, (user.id, item.id))
        if not tracked:
            await message.answer("Этот предмет не отслеживается.")
            return
        await session.delete(tracked)
        await session.commit()
        await message.answer(f"Предмет '{item.market_hash_name}' удалён из отслеживания.")

# --------------------- /unsubscribe ---------------------
@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /unsubscribe <название предмета> [daily|weekly]")
        return
    parts = args[1].split()
    period = None
    if parts[-1].lower() in ('daily', 'weekly'):
        period = parts[-1].lower()
        name = " ".join(parts[:-1])
    else:
        name = " ".join(parts)

    async for session in get_db():
        stmt = select(Item).where(Item.market_hash_name.ilike(f"%{name}%"), Item.app_id == settings.APP_ID)
        result = await session.execute(stmt)
        items = result.scalars().all()
        if not items:
            await message.answer("Предмет не найден.")
            return
        item = items[0]
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала выполните /start")
            return

        # Строим запрос для удаления подписок
        query = select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.item_id == item.id
        )
        if period:
            query = query.where(Subscription.frequency == period)
        subs = (await session.execute(query)).scalars().all()
        if not subs:
            await message.answer("Нет активных подписок для этого предмета.")
            return
        for sub in subs:
            sub.active = False
        await session.commit()
        await message.answer(f"Подписки на '{item.market_hash_name}' отключены.")

# --------------------- /delete_alert ---------------------
@dp.message(Command("delete_alert"))
async def cmd_delete_alert(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /delete_alert <ID алерта> (список ID: /alerts)")
        return
    try:
        alert_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    async for session in get_db():
        user = await session.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала выполните /start")
            return
        alert = await session.get(PriceAlert, alert_id)
        if not alert or alert.user_id != user.id:
            await message.answer("Алерт не найден или не принадлежит вам.")
            return
        await session.delete(alert)
        await session.commit()
        await message.answer(f"Алерт с ID {alert_id} удалён.")

# --------------------- /help ---------------------
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📋 <b>Справка по командам:</b>\n\n"
        "/start - регистрация\n"
        "/link_steam - привязать Steam ID (получить можно на сайте steamid.uk)\n"
        "/inventory - ваш инвентарь из Steam\n"
        "/track <название> - начать отслеживание предмета\n"
        "/untrack <название> - прекратить отслеживание\n"
        "/stats <название> - статистика и график цены\n"
        "/subscribe <название> daily|weekly - подписаться на дайджест\n"
        "/unsubscribe <название> [daily|weekly] - отписаться\n"
        "/alert <название> <процент> [24h|7d] - создать алерт на изменение цены\n"
        "/alerts - список активных алертов\n"
        "/delete_alert <ID> - удалить алерт\n"
        "/help - эта справка"
    )
    await message.answer(text)

# --------------------- Callback: подписка из инвентаря ---------------------
@dp.callback_query(F.data.startswith("sub_add:"))
async def cb_sub_add(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Неверные данные")
        return
    item_id = int(parts[1])
    freq = parts[2]  # daily или weekly
    async for session in get_db():
        user = await session.get(User, callback.from_user.id)
        if not user:
            await callback.answer("Сначала /start")
            return
        item = await session.get(Item, item_id)
        if not item:
            await callback.answer("Предмет не найден")
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
        else:
            session.add(Subscription(user_id=user.id, item_id=item.id, frequency=freq))
        await session.commit()
        await callback.answer(f"Подписка {freq} активирована!")
        await callback.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("stats:"))
async def cb_stats(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    async for session in get_db():
        item = await session.get(Item, item_id)
        if item:
            # имитируем команду /stats с названием предмета
            await cmd_stats(callback.message, item.market_hash_name)  # переиспользуем логику
    await callback.answer()

@dp.callback_query(F.data.startswith("subs:"))
async def cb_subs(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    await callback.message.answer("Выберите период:", reply_markup=subscription_choice(item_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("alert:"))
async def cb_alert(callback: types.CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    # переводим пользователя в состояние ввода процента
    # можно реализовать через FSM
    await callback.answer("В разработке")