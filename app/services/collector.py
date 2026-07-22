import logging
from datetime import date, datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Item, ItemDailyStats, ItemSnapshot, UserTrackedItem
from app.services.steam_client import SteamClient

logger = logging.getLogger(__name__)

async def update_snapshots(session: AsyncSession, steam_client: SteamClient, app_id: int):
    """Обновляет снапшоты всех отслеживаемых предметов."""
    # Получаем все предметы, у которых есть трекеры или is_tracked
    stmt = select(Item).where(
        (Item.is_tracked == True) | 
        (Item.id.in_(select(UserTrackedItem.item_id.distinct()))
    )).distinct()
    result = await session.execute(stmt)
    items = result.scalars().all()

    logger.info(f"Updating snapshots for {len(items)} items")
    for item in items:
        try:
            data = await steam_client.get_price_overview(app_id, item.market_hash_name)
            if not data.get("success"):
                logger.warning(f"No price data for {item.market_hash_name}")
                continue

            lowest_price = float(data.get("lowest_price", "0").replace("$", "").replace(",", ""))
            median_price = float(data.get("median_price", "0").replace("$", "").replace(",", ""))
            volume = int(data.get("volume", "0").replace(",", ""))

            # Обновляем или создаем снапшот
            snapshot = await session.get(ItemSnapshot, item.id)
            if not snapshot:
                snapshot = ItemSnapshot(item_id=item.id)
                session.add(snapshot)

            # Сохраняем старую цену для price_24h_ago
            if snapshot.median_price and snapshot.median_price != median_price:
                snapshot.price_24h_ago = snapshot.median_price
            elif not snapshot.price_24h_ago:
                # Попытка взять из истории за предыдущий день
                yesterday = date.today() - date.resolution
                stmt_hist = select(ItemDailyStats).where(
                    ItemDailyStats.item_id == item.id,
                    ItemDailyStats.date == yesterday
                )
                hist_result = await session.execute(stmt_hist)
                hist_entry = hist_result.scalar_one_or_none()
                if hist_entry:
                    snapshot.price_24h_ago = hist_entry.price

            snapshot.lowest_price = lowest_price
            snapshot.median_price = median_price
            snapshot.volume_24h = volume
            snapshot.updated_at = datetime.now(timezone.utc)

            # Обновляем дневную статистику (если сегодня ещё нет)
            today = date.today()
            stmt_day = select(ItemDailyStats).where(
                ItemDailyStats.item_id == item.id,
                ItemDailyStats.date == today
            )
            day_result = await session.execute(stmt_day)
            day_stat = day_result.scalar_one_or_none()
            if not day_stat:
                day_stat = ItemDailyStats(item_id=item.id, date=today, price=median_price, volume=volume)
                session.add(day_stat)
            else:
                day_stat.price = median_price
                day_stat.volume = volume

            await session.flush()
        except Exception as e:
            logger.error(f"Error updating {item.market_hash_name}: {e}")
    await session.commit()
    logger.info("Snapshots updated")

async def sync_daily_history(session: AsyncSession, steam_client: SteamClient, app_id: int):
    """Добирает историю для всех отслеживаемых предметов."""
    stmt = select(Item).where(Item.is_tracked == True)
    result = await session.execute(stmt)
    items = result.scalars().all()
    logger.info(f"Syncing daily history for {len(items)} items")
    for item in items:
        try:
            prices = await steam_client.get_price_history(app_id, item.market_hash_name)
            for entry in prices:
                # entry format: ["Jul 16 2026 01: +0", 12.345, "123"]
                date_str, price, volume = entry[0], entry[1], int(entry[2])
                # парсим дату (формат зависит от локали, упрощенно)
                dt = datetime.strptime(date_str[:11], "%b %d %Y").date()
                # проверяем, есть ли уже
                stmt_ex = select(ItemDailyStats).where(
                    ItemDailyStats.item_id == item.id,
                    ItemDailyStats.date == dt
                )
                res = await session.execute(stmt_ex)
                if not res.scalar_one_or_none():
                    session.add(ItemDailyStats(item_id=item.id, date=dt, price=price, volume=volume))
            await session.flush()
        except Exception as e:
            logger.error(f"History sync error for {item.market_hash_name}: {e}")
    await session.commit()
    logger.info("History synced")