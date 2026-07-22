import pytest
from app.db.models import User, Item, UserTrackedItem, ItemDailyStats, ItemSnapshot, Subscription, PriceAlert
from datetime import date, datetime, timezone

@pytest.mark.asyncio
async def test_create_user(session):
    user = User(id=123, chat_id=123)
    session.add(user)
    await session.commit()
    result = await session.get(User, 123)
    assert result.chat_id == 123

@pytest.mark.asyncio
async def test_create_item(session):
    item = Item(app_id=730, market_hash_name="AK-47 | Redline", name="AK-47 | Redline")
    session.add(item)
    await session.commit()
    result = await session.get(Item, item.id)
    assert result.market_hash_name == "AK-47 | Redline"

@pytest.mark.asyncio
async def test_user_tracked_item(session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="Test Item", name="Test")
    session.add_all([user, item])
    await session.commit()
    uti = UserTrackedItem(user_id=user.id, item_id=item.id)
    session.add(uti)
    await session.commit()
    # проверка
    from sqlalchemy import select
    stmt = select(UserTrackedItem).where(UserTrackedItem.user_id == 1)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    assert len(rows) == 1

# Добавить тесты для daily_stats, snapshot, subscription, alert - аналогично