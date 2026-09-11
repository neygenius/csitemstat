from __future__ import annotations

from app.db.models import (
    Item,
    ItemSnapshot,
    PriceAlert,
    Subscription,
    User,
)


async def test_user_created_at_autoset(session):
    user = User(id=1, chat_id=1)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    assert user.created_at is not None
    assert user.created_at.tzinfo is not None


async def test_item_is_tracked_default_false(session):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()
    await session.refresh(item)
    assert item.is_tracked is False


async def test_subscription_active_default_true(session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    sub = Subscription(user_id=user.id, item_id=item.id, frequency="daily")
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    assert sub.active is True
    assert sub.last_sent_at is None
    assert sub.created_at is not None


async def test_price_alert_defaults(session):
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    alert = PriceAlert(
        user_id=user.id, item_id=item.id, percent_change=10, period="24h"
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    assert alert.active is True
    assert alert.last_triggered_at is None
    assert alert.created_at is not None


async def test_item_snapshot_updated_at_not_default(session):
    """updated_at не имеет default — заполняется кодом."""
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    snap = ItemSnapshot(item_id=item.id, lowest_price=1, median_price=2)
    session.add(snap)
    await session.commit()
    await session.refresh(snap)
    assert snap.updated_at is None
