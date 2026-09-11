from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import (
    Item,
    ItemDailyStats,
    ItemSnapshot,
    PriceAlert,
    Subscription,
    User,
    UserTrackedItem,
)


async def test_user_tracked_items_relationship(session):
    user = User(id=1, chat_id=1)
    item1 = Item(app_id=730, market_hash_name="A", name="A")
    item2 = Item(app_id=730, market_hash_name="B", name="B")
    session.add_all([user, item1, item2])
    await session.commit()

    session.add_all(
        [
            UserTrackedItem(user_id=user.id, item_id=item1.id),
            UserTrackedItem(user_id=user.id, item_id=item2.id),
        ]
    )
    await session.commit()

    stmt = (
        select(User).where(User.id == user.id).options(selectinload(User.tracked_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()
    assert len(loaded.tracked_items) == 2


async def test_item_snapshot_optional(session):
    item = Item(app_id=730, market_hash_name="A", name="A")
    session.add(item)
    await session.commit()

    stmt = select(Item).where(Item.id == item.id).options(selectinload(Item.snapshot))
    loaded = (await session.execute(stmt)).scalar_one()
    assert loaded.snapshot is None

    session.add(ItemSnapshot(item_id=item.id, lowest_price=1, median_price=2))
    await session.commit()

    session.expire_all()

    loaded = (await session.execute(stmt)).scalar_one()
    assert loaded.snapshot is not None
    assert float(loaded.snapshot.median_price) == 2.0


async def test_item_daily_stats_relationship(session):
    item = Item(app_id=730, market_hash_name="A", name="A")
    session.add(item)
    await session.commit()

    session.add_all(
        [
            ItemDailyStats(item_id=item.id, date=date(2026, 1, 1), price=1, volume=10),
            ItemDailyStats(item_id=item.id, date=date(2026, 1, 2), price=2, volume=20),
        ]
    )
    await session.commit()

    stmt = (
        select(Item).where(Item.id == item.id).options(selectinload(Item.daily_stats))
    )
    loaded = (await session.execute(stmt)).scalar_one()
    assert len(loaded.daily_stats) == 2


async def test_user_subscriptions_and_alerts(session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="A", name="A")
    session.add_all([user, item])
    await session.commit()

    session.add_all(
        [
            Subscription(user_id=user.id, item_id=item.id, frequency="daily"),
            Subscription(user_id=user.id, item_id=item.id, frequency="weekly"),
            PriceAlert(
                user_id=user.id, item_id=item.id, percent_change=10, period="24h"
            ),
            PriceAlert(user_id=user.id, item_id=item.id, percent_change=5, period="7d"),
        ]
    )
    await session.commit()

    stmt = (
        select(User)
        .where(User.id == user.id)
        .options(
            selectinload(User.subscriptions),
            selectinload(User.price_alerts),
        )
    )
    loaded = (await session.execute(stmt)).scalar_one()
    assert len(loaded.subscriptions) == 2
    assert len(loaded.price_alerts) == 2
