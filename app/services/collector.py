import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from redis.asyncio.client import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.state as app_state
from app.db.models import (
    Item,
    ItemDailyStats,
    ItemHourlyStats,
    ItemSnapshot,
    UserTrackedItem,
)
from app.services.statistics import compute_trend
from app.services.steam_client import SteamClient

logger = logging.getLogger(__name__)


async def update_snapshots(
    session: AsyncSession, steam_client: SteamClient, app_id: int
) -> None:
    """
    Обновляет снапшоты всех отслеживаемых предметов.
    """
    stmt = (
        select(Item)
        .where(
            (Item.is_tracked == True)
            | (Item.id.in_(select(UserTrackedItem.item_id.distinct())))
        )
        .distinct()
    )
    result = await session.execute(stmt)
    items = result.scalars().all()

    logger.info(f"Updating snapshots for {len(items)} items")

    for item in items:
        try:
            await ensure_item_history(session, steam_client, item)

            data = await steam_client.get_price_overview(app_id, item.market_hash_name)
            if not data or not data.get("success"):
                logger.warning(f"No price data for {item.market_hash_name}")
                continue

            lowest_price = parse_steam_price(data.get("lowest_price", "0"))
            median_price = parse_steam_price(data.get("median_price", "0"))
            volume = int(re.sub(r"[^\d]", "", data.get("volume", "0")))

            snapshot = await session.get(ItemSnapshot, item.id)
            if not snapshot:
                snapshot = ItemSnapshot(item_id=item.id)
                session.add(snapshot)

            snapshot.lowest_price = lowest_price
            snapshot.median_price = median_price
            snapshot.volume_24h = volume
            snapshot.updated_at = datetime.now(timezone.utc)

            # Получаем цену 24 часа назад (из часовых данных или вчерашней дневной)
            snapshot.price_24h_ago = await get_price_24h_ago(session, item.id)

            # Обновляем дневную статистику за сегодня
            today_utc = datetime.now(timezone.utc).date()
            day_stat = await session.get(ItemDailyStats, (item.id, today_utc))
            if not day_stat:
                day_stat = ItemDailyStats(
                    item_id=item.id, date=today_utc, price=median_price, volume=volume
                )
                session.add(day_stat)
            else:
                day_stat.price = median_price
                day_stat.volume = volume

            # Вычисляем и сохраняем тренд
            slope, direction = await compute_trend(session, item.id)
            snapshot.trend_slope = slope
            snapshot.trend_direction = direction

            await session.flush()

            # Инвалидируем кэш графиков
            await invalidate_price_chart_cache(app_state.redis_client, item.id)

        except Exception:
            logger.exception(f"Error updating {item.market_hash_name}")

    await session.commit()
    logger.info("Snapshots updated")


async def sync_daily_history(
    session: AsyncSession, steam_client: SteamClient, app_id: int
) -> None:
    """
    Синхронизирует историю цен для всех отслеживаемых предметов.
    """
    stmt = select(Item).where(Item.is_tracked == True)
    result = await session.execute(stmt)
    items = result.scalars().all()

    logger.info(f"Syncing daily history for {len(items)} items")

    for item in items:
        try:
            await save_hourly_history(session, steam_client, item, days=1)
            await aggregate_hourly_to_daily(session, item.id)
            await session.flush()
            await invalidate_price_chart_cache(app_state.redis_client, item.id)

        except Exception:
            logger.exception(f"History sync error for {item.market_hash_name}")

    await session.commit()
    logger.info("History synced")


def parse_steam_price(price_str: str) -> float:
    """
    Извлекает числовое значение из строки цены Steam.
    """
    clean = re.sub(r"[^\d.,]", "", price_str)
    if not clean:
        return 0.0
    if "," in clean and "." not in clean:
        clean = clean.replace(",", ".")
    elif "," in clean and "." in clean:
        if clean.rfind(".") > clean.rfind(","):
            clean = clean.replace(",", "")
        else:
            clean = clean.replace(".", "").replace(",", ".")
    return float(clean)


async def ensure_item_history(
    session: AsyncSession, steam_client: SteamClient, item: Item
) -> None:
    """
    Загружает полную историю предмета, разделяя часовые и дневные данные.
    """
    hourly_count = await session.scalar(
        select(func.count())
        .select_from(ItemHourlyStats)
        .where(ItemHourlyStats.item_id == item.id)
    )
    daily_count = await session.scalar(
        select(func.count())
        .select_from(ItemDailyStats)
        .where(ItemDailyStats.item_id == item.id)
    )

    if hourly_count > 0 and daily_count > 0:
        logger.info(f"History for {item.market_hash_name} already exist")
        return

    logger.info(f"Loading full price history for {item.market_hash_name}")
    prices = await steam_client.get_price_history(item.app_id, item.market_hash_name)
    if not prices:
        logger.warning(f"No history returned for {item.market_hash_name}")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    for entry in prices:
        date_str = entry[0]
        price = entry[1]
        volume = int(entry[2])

        try:
            dt = datetime.strptime(date_str, "%b %d %Y %H: +0").replace(
                tzinfo=timezone.utc
            )
        except ValueError as e:
            logger.warning(f"Failed to parse date '{date_str}': {e}")
            continue

        if dt >= cutoff:
            exists = await session.get(ItemHourlyStats, (item.id, dt))
            if not exists:
                session.add(
                    ItemHourlyStats(
                        item_id=item.id, timestamp=dt, price=price, volume=volume
                    )
                )
        else:
            day = dt.date()
            exists = await session.get(ItemDailyStats, (item.id, day))
            if not exists:
                session.add(
                    ItemDailyStats(
                        item_id=item.id, date=day, price=price, volume=volume
                    )
                )

    await session.flush()
    await aggregate_hourly_to_daily(session, item.id)
    logger.info(f"Loaded {len(prices)} history records for {item.market_hash_name}")


async def save_hourly_history(
    session: AsyncSession, steam_client: SteamClient, item: Item, days: int = 30
) -> None:
    """
    Загружает и сохраняет только часовые данные за последние N дней.
    """
    prices = await steam_client.get_price_history(item.app_id, item.market_hash_name)
    if not prices:
        logger.warning(f"No history returned for {item.market_hash_name}")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for entry in prices:
        date_str = entry[0]
        price = entry[1]
        volume = int(entry[2])

        try:
            dt = datetime.strptime(date_str, "%b %d %Y %H: +0").replace(
                tzinfo=timezone.utc
            )
        except ValueError as e:
            logger.warning(f"Failed to parse date '{date_str}': {e}")
            continue

        if dt >= cutoff:
            continue

        exists = await session.get(ItemHourlyStats, (item.id, dt))
        if not exists:
            session.add(
                ItemHourlyStats(
                    item_id=item.id, timestamp=dt, price=price, volume=volume
                )
            )

    await session.flush()


async def aggregate_hourly_to_daily(session, item_id) -> None:
    """
    Агрегирует часовые данные в дневные для конкретного предмета.
    """
    stmt = (
        select(ItemHourlyStats)
        .where(ItemHourlyStats.item_id == item_id)
        .order_by(ItemHourlyStats.timestamp)
    )
    hourly_records = (await session.execute(stmt)).scalars().all()

    daily_data = defaultdict(list)
    for hr in hourly_records:
        day = hr.timestamp.date()
        daily_data[day].append(hr)

    for day, hrs in daily_data.items():
        avg_price = sum(float(h.price) for h in hrs) / len(hrs)
        total_volume = sum(h.volume for h in hrs)

        day_stat = await session.get(ItemDailyStats, (item_id, day))
        if day_stat:
            day_stat.price = avg_price
            day_stat.volume = total_volume
        else:
            session.add(
                ItemDailyStats(
                    item_id=item_id, date=day, price=avg_price, volume=total_volume
                )
            )

    await session.flush()


async def get_price_24h_ago(session: AsyncSession, item_id: int) -> float | None:
    """
    Возвращает цену ровно 24 часа назад, если возможно.
    """
    target_time = datetime.now(timezone.utc) - timedelta(hours=24)

    # Ищем самую позднюю часовую запись, которая не старше 24 часов
    stmt = (
        select(ItemHourlyStats.price)
        .where(
            ItemHourlyStats.item_id == item_id, ItemHourlyStats.timestamp <= target_time
        )
        .order_by(ItemHourlyStats.timestamp.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    price = result.scalar_one_or_none()
    if price is not None:
        return float(price)

    # Если часовых нет, берём вчерашнюю дневную
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    stmt = select(ItemDailyStats.price).where(
        ItemDailyStats.item_id == item_id, ItemDailyStats.date == yesterday
    )
    result = await session.execute(stmt)
    price = result.scalar_one_or_none()
    if price is not None:
        return float(price)

    return None


async def update_single_item_snapshot(
    session: AsyncSession, steam_client: SteamClient, item: Item
) -> bool:
    """
    Обновляет снапшот и дневную статистику для одного предмета.
    """
    try:
        await ensure_item_history(session, steam_client, item)

        data = await steam_client.get_price_overview(item.app_id, item.market_hash_name)
        if not data or not data.get("success"):
            logger.warning(f"No price data for {item.market_hash_name}")
            return False

        lowest_price = parse_steam_price(data.get("lowest_price", "0"))
        median_price = parse_steam_price(data.get("median_price", "0"))
        volume = int(re.sub(r"[^\d]", "", data.get("volume", "0")))

        snapshot = await session.get(ItemSnapshot, item.id)
        if not snapshot:
            snapshot = ItemSnapshot(item_id=item.id)
            session.add(snapshot)

        # Обновляем снапшот
        snapshot.lowest_price = lowest_price
        snapshot.median_price = median_price
        snapshot.volume_24h = volume
        snapshot.updated_at = datetime.now(timezone.utc)

        # Пытаемся установить price_24h_ago из вчерашней истории
        yesterday = datetime.now(tz=timezone.utc).date() - timedelta(days=1)
        stmt_hist = select(ItemDailyStats.price).where(
            ItemDailyStats.item_id == item.id, ItemDailyStats.date == yesterday
        )
        hist_result = await session.execute(stmt_hist)
        old_price = hist_result.scalar_one_or_none()
        if old_price is not None:
            snapshot.price_24h_ago = float(old_price)

        # Добавляем/обновляем запись в дневной статистике
        today = datetime.now(tz=timezone.utc).date()
        day_stat = await session.get(ItemDailyStats, (item.id, today))
        if not day_stat:
            day_stat = ItemDailyStats(
                item_id=item.id, date=today, price=median_price, volume=volume
            )
            session.add(day_stat)
        else:
            day_stat.price = median_price
            day_stat.volume = volume

        slope, direction = await compute_trend(session, item.id)
        snapshot.trend_slope = slope
        snapshot.trend_direction = direction

        await session.commit()
        logger.info(f"Snapshot {item.market_hash_name} updated successfully")

        await invalidate_price_chart_cache(app_state.redis_client, item.id)
        return True

    except Exception:
        logger.exception(f"Failed to update snapshot for {item.market_hash_name}")
        await session.rollback()
        return False


async def invalidate_price_chart_cache(redis_client: Redis, item_id: int):
    """
    Удаляет все закэшированные графики для указанного предмета.
    """
    if not redis_client:
        return
    pattern = f"plot:{item_id}:*"
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
        if keys:
            await redis_client.delete(*keys)
        if cursor == 0:
            break
