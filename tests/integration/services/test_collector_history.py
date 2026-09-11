from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.db.models import Item, ItemDailyStats, ItemHourlyStats
from app.services.collector import (
    aggregate_hourly_to_daily,
    ensure_item_history,
)

pytestmark = pytest.mark.integration


def _steam_date(dt: datetime) -> str:
    """Формат, который ожидает collector: '%b %d %Y %H: +0'."""
    return dt.strftime("%b %d %Y %H: +0")


async def _count(session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for col, val in filters.items():
        stmt = stmt.where(getattr(model, col) == val)
    return await session.scalar(stmt)


async def test_ensure_item_history_splits_by_cutoff(session):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=5)  # < cutoff → hourly
    old = now - timedelta(days=60)  # > cutoff → daily

    client = AsyncMock()
    client.get_price_history = AsyncMock(
        return_value=[
            [_steam_date(recent), 10.0, "100"],
            [_steam_date(old), 5.0, "50"],
        ]
    )

    await ensure_item_history(session, client, item)

    hourly = await _count(session, ItemHourlyStats, item_id=item.id)
    daily = await _count(session, ItemDailyStats, item_id=item.id)
    assert hourly == 1
    assert daily >= 1  # старые попадают в daily + агрегация из hourly


async def test_ensure_item_history_skips_when_data_exists(session):
    """Если часовые и дневные записи уже есть — Steam не дёргается."""
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    now = datetime.now(timezone.utc)
    session.add(
        ItemHourlyStats(
            item_id=item.id,
            timestamp=now - timedelta(hours=1),
            price=1,
            volume=1,
        )
    )
    session.add(
        ItemDailyStats(
            item_id=item.id,
            date=now.date() - timedelta(days=60),
            price=1,
            volume=1,
        )
    )
    await session.commit()

    client = AsyncMock()
    client.get_price_history = AsyncMock()

    await ensure_item_history(session, client, item)

    client.get_price_history.assert_not_awaited()


async def test_ensure_item_history_skips_invalid_dates(session):
    """Невалидные даты пропускаются, остальные обрабатываются."""
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    recent = datetime.now(timezone.utc) - timedelta(days=3)
    client = AsyncMock()
    client.get_price_history = AsyncMock(
        return_value=[
            ["garbage-date", 1.0, "1"],
            [_steam_date(recent), 10.0, "100"],
        ]
    )

    await ensure_item_history(session, client, item)

    assert await _count(session, ItemHourlyStats, item_id=item.id) == 1


async def test_ensure_item_history_no_history_noop(session):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    client = AsyncMock()
    client.get_price_history = AsyncMock(return_value=[])

    await ensure_item_history(session, client, item)

    assert await _count(session, ItemDailyStats, item_id=item.id) == 0
    assert await _count(session, ItemHourlyStats, item_id=item.id) == 0


async def test_aggregate_hourly_to_daily_computes_avg_and_sum(session):
    """Средневзвешенная цена за день и суммарный объём."""
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    target_day = datetime.now(timezone.utc).date() - timedelta(days=1)
    for hour, price, vol in [(1, 10.0, 100), (2, 12.0, 200), (3, 14.0, 300)]:
        session.add(
            ItemHourlyStats(
                item_id=item.id,
                timestamp=datetime.combine(target_day, datetime.min.time()).replace(
                    hour=hour, tzinfo=timezone.utc
                ),
                price=price,
                volume=vol,
            )
        )
    await session.commit()

    await aggregate_hourly_to_daily(session, item.id)

    stat = await session.get(ItemDailyStats, (item.id, target_day))
    assert stat is not None
    assert float(stat.price) == 12.0  # (10 + 12 + 14) / 3
    assert stat.volume == 600  # 100 + 200 + 300


async def test_aggregate_hourly_to_daily_updates_existing(session):
    """Если дневная запись уже есть — она обновляется, а не дублируется."""
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    target_day = datetime.now(timezone.utc).date() - timedelta(days=1)
    session.add(
        ItemDailyStats(
            item_id=item.id,
            date=target_day,
            price=1.0,
            volume=1,
        )
    )
    session.add(
        ItemHourlyStats(
            item_id=item.id,
            timestamp=datetime.combine(target_day, datetime.min.time()).replace(
                hour=1,
                tzinfo=timezone.utc,
            ),
            price=20.0,
            volume=500,
        )
    )
    await session.commit()

    await aggregate_hourly_to_daily(session, item.id)

    assert await _count(session, ItemDailyStats, item_id=item.id) == 1
    stat = await session.get(ItemDailyStats, (item.id, target_day))
    assert float(stat.price) == 20.0
    assert stat.volume == 500
