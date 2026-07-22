import pytest
from app.services.statistics import compute_trend, percent_change
from datetime import date, timedelta
from app.db.models import Item, ItemDailyStats

@pytest.mark.asyncio
async def test_compute_trend(session):
    item = Item(app_id=730, market_hash_name="TrendItem")
    session.add(item)
    await session.commit()
    # Добавляем точки с растущей ценой
    for i, price in enumerate([10, 11, 12, 13, 14, 15, 16]):
        session.add(ItemDailyStats(item_id=item.id, date=date.today() - timedelta(days=6-i), price=price, volume=100))
    await session.commit()
    slope, direction = await compute_trend(session, item.id, window_days=7)
    assert slope > 0
    assert direction == "up"

@pytest.mark.asyncio
async def test_compute_trend_stable(session):
    item = Item(app_id=730, market_hash_name="StableItem")
    session.add(item)
    await session.commit()
    for i in range(7):
        session.add(ItemDailyStats(item_id=item.id, date=date.today() - timedelta(days=6-i), price=10.0, volume=100))
    await session.commit()
    slope, direction = await compute_trend(session, item.id)
    assert direction == "stable"

def test_percent_change():
    assert percent_change(110, 100) == 10.0
    assert percent_change(90, 100) == -10.0
    assert percent_change(0, 100) == -100.0
    assert percent_change(100, 0) == 0.0