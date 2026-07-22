import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from app.services.collector import update_snapshots, sync_daily_history
from app.db.models import Item, ItemSnapshot, ItemDailyStats, UserTrackedItem, User
from datetime import date, datetime, timezone

@pytest.mark.asyncio
async def test_update_snapshots(session, steam_client_mock):
    # Добавляем предмет и трекер
    item = Item(app_id=730, market_hash_name="TestItem", is_tracked=True)
    user = User(id=1, chat_id=1)
    session.add_all([item, user])
    await session.commit()
    session.add(UserTrackedItem(user_id=1, item_id=item.id))
    await session.commit()

    # Настраиваем мок SteamClient
    steam_client_mock.get_price_overview.return_value = {
        "success": True,
        "lowest_price": "$5.00",
        "median_price": "$6.50",
        "volume": "200"
    }

    await update_snapshots(session, steam_client_mock, app_id=730)

    # Проверяем снапшот
    snapshot = await session.get(ItemSnapshot, item.id)
    assert snapshot is not None
    assert float(snapshot.median_price) == 6.50
    assert float(snapshot.lowest_price) == 5.00
    assert snapshot.volume_24h == 200

    # Проверяем дневную статистику
    today = date.today()
    stmt = select(ItemDailyStats).where(ItemDailyStats.item_id == item.id, ItemDailyStats.date == today)
    result = await session.execute(stmt)
    day_stat = result.scalar_one()
    assert float(day_stat.price) == 6.50
    assert day_stat.volume == 200

@pytest.mark.asyncio
async def test_sync_daily_history(session, steam_client_mock):
    item = Item(app_id=730, market_hash_name="HistoryItem", is_tracked=True)
    session.add(item)
    await session.commit()

    # Возвращаем массив точек истории
    steam_client_mock.get_price_history.return_value = [
        ["Jul 20 2026 01: +0", 10.0, "123"],
        ["Jul 21 2026 01: +0", 11.0, "150"]
    ]

    await sync_daily_history(session, steam_client_mock, app_id=730)

    # Проверяем, что данные сохранены
    stmt = select(ItemDailyStats).where(ItemDailyStats.item_id == item.id).order_by(ItemDailyStats.date)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    assert len(rows) == 2
    assert rows[0].date == date(2026, 7, 20)
    assert float(rows[1].price) == 11.0