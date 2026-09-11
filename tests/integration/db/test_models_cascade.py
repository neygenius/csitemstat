from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db.models import (
    Item,
    ItemDailyStats,
    ItemHourlyStats,
    ItemSnapshot,
    PriceAlert,
    Subscription,
    User,
    UserTrackedItem,
)


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_delete_user_cascades(session):
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
    session.add(Subscription(user_id=user.id, item_id=item.id, frequency="daily"))
    session.add(
        PriceAlert(user_id=user.id, item_id=item.id, percent_change=10, period="24h")
    )
    await session.commit()

    assert await _count(session, UserTrackedItem) == 1
    assert await _count(session, Subscription) == 1
    assert await _count(session, PriceAlert) == 1

    await session.delete(user)
    await session.commit()

    assert await _count(session, UserTrackedItem) == 0
    assert await _count(session, Subscription) == 0
    assert await _count(session, PriceAlert) == 0
    # Item остался
    assert await _count(session, Item) == 1


async def test_delete_item_cascades(session):
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
    session.add(Subscription(user_id=user.id, item_id=item.id, frequency="daily"))
    session.add(
        PriceAlert(user_id=user.id, item_id=item.id, percent_change=10, period="24h")
    )
    session.add(ItemSnapshot(item_id=item.id, lowest_price=1, median_price=2))
    session.add(
        ItemDailyStats(
            item_id=item.id,
            date=datetime.now(tz=timezone.utc).date(),
            price=1,
            volume=1,
        )
    )
    session.add(
        ItemHourlyStats(
            item_id=item.id, timestamp=datetime.now(timezone.utc), price=1, volume=1
        )
    )
    await session.commit()

    await session.delete(item)
    await session.commit()

    assert await _count(session, UserTrackedItem) == 0
    assert await _count(session, Subscription) == 0
    assert await _count(session, PriceAlert) == 0
    assert await _count(session, ItemSnapshot) == 0
    assert await _count(session, ItemDailyStats) == 0
    assert await _count(session, ItemHourlyStats) == 0
    # User остался
    assert await _count(session, User) == 1


async def test_delete_user_does_not_touch_other_users_data(session):
    u1 = User(id=1, chat_id=100)
    u2 = User(id=2, chat_id=200)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([u1, u2, item])
    await session.commit()

    session.add(UserTrackedItem(user_id=u1.id, item_id=item.id))
    session.add(UserTrackedItem(user_id=u2.id, item_id=item.id))
    await session.commit()

    await session.delete(u1)
    await session.commit()

    rows = (await session.execute(select(UserTrackedItem))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == u2.id
