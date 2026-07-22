import logging
from datetime import datetime, timezone
from typing import List
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db.models import PriceAlert, ItemSnapshot, ItemDailyStats, Subscription, User, Item
from app.services.statistics import percent_change
from app.bot.messages import send_telegram_message

logger = logging.getLogger(__name__)

async def check_price_alerts(session: AsyncSession, bot_token: str):
    """Проверяет все активные алерты и отправляет уведомления."""
    stmt = select(PriceAlert).where(PriceAlert.active == True)
    result = await session.execute(stmt)
    alerts = result.scalars().all()

    for alert in alerts:
        snapshot = await session.get(ItemSnapshot, alert.item_id)
        if not snapshot or snapshot.median_price is None:
            continue

        # Определяем старую цену в зависимости от периода
        if alert.period == '24h':
            old_price = snapshot.price_24h_ago
        else:  # 7d
            seven_days_ago = date.today() - timedelta(days=7)
            stmt_hist = select(ItemDailyStats.price).where(
                ItemDailyStats.item_id == alert.item_id,
                ItemDailyStats.date == seven_days_ago
            )
            hist_result = await session.execute(stmt_hist)
            old_price = hist_result.scalar_one_or_none()

        if old_price is None or old_price == 0:
            continue

        change = percent_change(float(snapshot.median_price), float(old_price))
        if abs(change) >= float(alert.percent_change):
            # Получаем имя предмета отдельным запросом, избегая ленивой загрузки
            item = await session.get(Item, alert.item_id)
            item_name = item.name if item else f"ID {alert.item_id}"
            user = await session.get(User, alert.user_id)
            if user:
                direction = "↑" if change > 0 else "↓"
                text = (
                    f"⚠️ Ценовой алерт\n"
                    f"{item_name} (ID: {alert.item_id})\n"
                    f"Цена изменилась на {direction} {abs(change):.1f}% за {alert.period}\n"
                    f"Текущая: {float(snapshot.median_price):.2f} {settings.CURRENCY_SYMBOL}"
                )
                await send_telegram_message(bot_token, user.chat_id, text)
                alert.last_triggered_at = datetime.now(timezone.utc)  # фиксируем UTC
                session.add(alert)
    await session.commit()

async def send_digests(session: AsyncSession, bot_token: str, frequency: str):
    """Рассылает дайджесты с заданной периодичностью (daily/weekly)."""
    stmt = select(Subscription).where(
        Subscription.active == True,
        Subscription.frequency == frequency
    )
    result = await session.execute(stmt)
    subscriptions = result.scalars().all()

    for sub in subscriptions:
        snapshot = await session.get(ItemSnapshot, sub.item_id)
        if not snapshot:
            continue

        # Вычисляем изменение за соответствующий период
        if frequency == 'daily':
            old_price = snapshot.price_24h_ago
            period_text = "за сутки"
        else:
            seven_days_ago = date.today() - timedelta(days=7)
            stmt_hist = select(ItemDailyStats.price).where(
                ItemDailyStats.item_id == sub.item_id,
                ItemDailyStats.date == seven_days_ago
            )
            hist_result = await session.execute(stmt_hist)
            old_price = hist_result.scalar_one_or_none()
            period_text = "за неделю"

        change_str = "Н/Д"
        if old_price and float(old_price) != 0:
            change = percent_change(float(snapshot.median_price), float(old_price))
            direction = "↑" if change > 0 else ("↓" if change < 0 else "→")
            change_str = f"{direction} {abs(change):.1f}%"

        # Имя предмета загружаем через отдельный объект, чтобы не тянуть отношение лениво
        item = await session.get(Item, sub.item_id)
        item_name = item.market_hash_name if item else "Неизвестный предмет"

        text = (
            f"📊 {'Ежедневный' if frequency == 'daily' else 'Еженедельный'} дайджест\n"
            f"Предмет: {item_name}\n"
            f"Текущая цена: {float(snapshot.median_price):.2f} {settings.CURRENCY_SYMBOL}\n"
            f"Изменение {period_text}: {change_str}\n"
            f"Тренд: {snapshot.trend_direction}"
        )
        user = await session.get(User, sub.user_id)
        if user:
            await send_telegram_message(bot_token, user.chat_id, text)
            sub.last_sent_at = datetime.now(timezone.utc)  # UTC
            session.add(sub)
    await session.commit()