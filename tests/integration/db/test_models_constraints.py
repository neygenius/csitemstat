from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Item,
    ItemDailyStats,
    Subscription,
    User,
    UserTrackedItem,
)


async def test_item_unique_app_market_hash_name(session):
    session.add(Item(app_id=730, market_hash_name="AK-47", name="AK-47"))
    await session.commit()

    session.add(Item(app_id=730, market_hash_name="AK-47", name="AK-47 duplicate"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_item_same_name_different_app(session):
    """Одинаковое имя, но разные app_id — допустимо."""
    session.add(Item(app_id=730, market_hash_name="Same", name="Same"))
    session.add(Item(app_id=440, market_hash_name="Same", name="Same"))
    await session.commit()
    # Обе записи сохранены
    from sqlalchemy import func, select

    count = await session.scalar(select(func.count()).select_from(Item))
    assert count == 2


async def test_subscription_unique_user_item_frequency(session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(Subscription(user_id=user.id, item_id=item.id, frequency="daily"))
    await session.commit()

    session.add(Subscription(user_id=user.id, item_id=item.id, frequency="daily"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_subscription_different_frequency_ok(session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(Subscription(user_id=user.id, item_id=item.id, frequency="daily"))
    session.add(Subscription(user_id=user.id, item_id=item.id, frequency="weekly"))
    await session.commit()


async def test_user_tracked_item_composite_pk(session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
    await session.commit()

    session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_item_required_fields(session):
    """app_id и market_hash_name обязательны."""
    session.add(Item(app_id=None, market_hash_name="X", name="X"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_user_chat_id_required(session):
    session.add(User(id=1, chat_id=None))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_item_daily_stats_required_price(session):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    session.add(
        ItemDailyStats(
            item_id=item.id,
            date=datetime.now(tz=timezone.utc).date(),
            price=None,
            volume=1,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
