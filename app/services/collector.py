import logging
from datetime import date, datetime, timezone, timedelta
from dateutil import parser as date_parser
import re
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Item, ItemDailyStats, ItemSnapshot, UserTrackedItem
from app.services.steam_client import SteamClient

logger = logging.getLogger(__name__)

async def update_snapshots(session: AsyncSession, steam_client: SteamClient, app_id: int):
    """Обновляет снапшоты всех отслеживаемых предметов"""
    stmt = select(Item).where(
        (Item.is_tracked == True) | 
        (Item.id.in_(select(UserTrackedItem.item_id.distinct()))
    )).distinct()
    result = await session.execute(stmt)
    items = result.scalars().all()

    logger.info(f"Updating snapshots for {len(items)} items")
    for item in items:
        try:
            await ensure_item_history(session, steam_client, item)

            data = await steam_client.get_price_overview(app_id, item.market_hash_name)
            if not data.get("success"):
                logger.warning(f"No price data for {item.market_hash_name}")
                continue

            lowest_price = parse_steam_price(data.get("lowest_price", "0"))
            median_price = parse_steam_price(data.get("median_price", "0"))
            volume = int(re.sub(r'[^\d]', '', data.get("volume", "0")))

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
                yesterday = date.today() - timedelta(days=1)
                stmt_hist = select(ItemDailyStats.price).where(
                    ItemDailyStats.item_id == item.id,
                    ItemDailyStats.date == yesterday
                )
                hist_result = await session.execute(stmt_hist)
                old_price = hist_result.scalar_one_or_none()
                if old_price is not None:
                    snapshot.price_24h_ago = float(old_price)

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
            logger.error(f"Error updating {item.market_hash_name}: {e}", exc_info=True)
    await session.commit()
    logger.info("Snapshots updated")

async def sync_daily_history(session: AsyncSession, steam_client: SteamClient, app_id: int):
    """Добирает историю для всех отслеживаемых предметов"""
    stmt = select(Item).where(Item.is_tracked == True)
    result = await session.execute(stmt)
    items = result.scalars().all()
    logger.info(f"Syncing daily history for {len(items)} items")
    for item in items:
        try:
            prices = await steam_client.get_price_history(app_id, item.market_hash_name)
            for entry in prices:
                # entry format: ["May 27 2015 01: +0", 338.982, "228789"]
                date_part = entry[0].split()[:3]  # ["May", "27", "2015"]
                date_str = " ".join(date_part)
                try:
                    dt = date_parser.parse(date_str).date()
                except (ValueError, TypeError) as e:
                    logger.error(f"Не удалось распарсить дату: {entry[0]} ({e})", exc_info=True)
                    continue

                price = entry[1]
                volume = int(entry[2])

                stmt_ex = select(ItemDailyStats).where(
                    ItemDailyStats.item_id == item.id,
                    ItemDailyStats.date == dt
                )
                res = await session.execute(stmt_ex)
                if not res.scalar_one_or_none():
                    session.add(ItemDailyStats(item_id=item.id, date=dt, price=price, volume=volume))
            await session.flush()
        except Exception as e:
            logger.error(f"History sync error for {item.market_hash_name}: {e}", exc_info=True)
    await session.commit()
    logger.info("History synced")

def parse_steam_price(price_str: str) -> float:
    """Извлекает числовое значение из строки цены Steam (любая валюта)"""
    # Удаляем всё, кроме цифр, точки и запятой
    clean = re.sub(r'[^\d.,]', '', price_str)
    if not clean:
        return 0.0
    # Если есть запятая и нет точки — запятая десятичный разделитель
    if ',' in clean and '.' not in clean:
        clean = clean.replace(',', '.')
    # Если есть и точка, и запятая — смотрим, что идёт последним (дробная часть)
    elif ',' in clean and '.' in clean:
        if clean.rfind('.') > clean.rfind(','):
            # точка — дробный разделитель, запятые — тысячи
            clean = clean.replace(',', '')
        else:
            # запятая — дробный разделитель, точки — тысячи
            clean = clean.replace('.', '').replace(',', '.')
    return float(clean)

async def ensure_item_history(session: AsyncSession, steam_client: SteamClient, item: Item) -> None:
    """
    Проверяет наличие истории для предмета и при необходимости загружает её из Steam.
    """
    stmt = select(func.count()).select_from(ItemDailyStats).where(ItemDailyStats.item_id == item.id)
    result = await session.execute(stmt)
    count = result.scalar()

    if count > 0:
        logger.info(f"History for {item.market_hash_name} already exist")
        return

    logger.info(f"Loading full price history for {item.market_hash_name}")
    prices = await steam_client.get_price_history(item.app_id, item.market_hash_name)

    for entry in prices:
        # entry: [date_str, price, volume_str]
        date_str = entry[0]
        price = entry[1]
        volume = int(entry[2])

        # Парсим дату (используем dateutil для надёжности)
        try:
            dt = date_parser.parse(date_str).date()
        except (ValueError, TypeError):
            logger.warning(f"Не удалось распарсить дату: {date_str}")
            continue

        # Проверяем, существует ли уже такая запись (на случай дублей)
        exists = await session.get(ItemDailyStats, (item.id, dt))
        if not exists:
            session.add(ItemDailyStats(item_id=item.id, date=dt, price=price, volume=volume))

    await session.commit()
    logger.info(f"Loaded {len(prices)} history records for {item.market_hash_name}")

async def update_single_item_snapshot(session: AsyncSession, steam_client: SteamClient, item: Item) -> bool:
    """
    Обновляет снапшот и дневную статистику для одного предмета.
    Возвращает True, если данные получены и сохранены, иначе False.
    """
    try:
        await ensure_item_history(session, steam_client, item)

        data = await steam_client.get_price_overview(item.app_id, item.market_hash_name)
        if not data or not data.get("success"):
            logger.warning(f"No price data for {item.market_hash_name}")
            return False

        lowest_price = parse_steam_price(data.get("lowest_price", "0"))
        median_price = parse_steam_price(data.get("median_price", "0"))
        volume = int(re.sub(r'[^\d]', '', data.get("volume", "0")))

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
        yesterday = date.today() - timedelta(days=1)
        stmt_hist = select(ItemDailyStats.price).where(
            ItemDailyStats.item_id == item.id,
            ItemDailyStats.date == yesterday
        )
        hist_result = await session.execute(stmt_hist)
        old_price = hist_result.scalar_one_or_none()
        if old_price is not None:
            snapshot.price_24h_ago = float(old_price)

        # Добавляем/обновляем запись в дневной статистике
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

        await session.commit()
        logger.info(f"Snapshot updated for {item.market_hash_name}")
        return True

    except Exception as e:
        logger.error(f"Failed to update snapshot for {item.market_hash_name}: {e}", exc_info=True)
        await session.rollback()
        return False