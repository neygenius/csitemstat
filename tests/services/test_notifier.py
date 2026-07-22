import pytest
from unittest.mock import AsyncMock, patch
from datetime import date, timedelta
from app.services.notifier import check_price_alerts, send_digests
from app.db.models import (
    User, Item, ItemSnapshot, ItemDailyStats,
    PriceAlert, Subscription
)

@pytest.mark.asyncio
async def test_check_price_alerts_triggers(session, redis_mock):
    user = User(id=1, chat_id=123)
    item = Item(id=1, app_id=730, market_hash_name="AlertItem")
    session.add_all([user, item])
    await session.commit()

    snap = ItemSnapshot(
        item_id=item.id,
        median_price=110.0,
        price_24h_ago=100.0
    )
    session.add(snap)
    await session.commit()

    alert = PriceAlert(
        user_id=user.id,
        item_id=item.id,
        percent_change=10.0,
        period="24h",
        active=True
    )
    session.add(alert)
    await session.commit()

    with patch('app.services.notifier.send_telegram_message', new_callable=AsyncMock) as mock_send:
        await check_price_alerts(session, "fake_bot_token")
        mock_send.assert_called_once()
        await session.refresh(alert)
        assert alert.last_triggered_at is not None

@pytest.mark.asyncio
async def test_check_price_alerts_no_trigger(session, redis_mock):
    user = User(id=2, chat_id=456)
    item = Item(id=2, app_id=730, market_hash_name="NoAlert")
    session.add_all([user, item])
    await session.commit()

    snap = ItemSnapshot(
        item_id=item.id,
        median_price=100.0,
        price_24h_ago=99.0
    )
    session.add(snap)
    await session.commit()

    alert = PriceAlert(
        user_id=user.id,
        item_id=item.id,
        percent_change=5.0,
        period="24h",
        active=True
    )
    session.add(alert)
    await session.commit()

    with patch('app.services.notifier.send_telegram_message', new_callable=AsyncMock) as mock_send:
        await check_price_alerts(session, "fake_token")
        mock_send.assert_not_called()

@pytest.mark.asyncio
async def test_send_daily_digest(session, redis_mock):
    user = User(id=3, chat_id=789)
    item = Item(id=3, app_id=730, market_hash_name="DailyItem")
    session.add_all([user, item])
    await session.commit()

    snap = ItemSnapshot(
        item_id=item.id,
        median_price=150.0,
        price_24h_ago=140.0,
        trend_direction="up"
    )
    session.add(snap)
    await session.commit()

    sub = Subscription(
        user_id=user.id,
        item_id=item.id,
        frequency="daily",
        active=True
    )
    session.add(sub)
    await session.commit()

    with patch('app.services.notifier.send_telegram_message', new_callable=AsyncMock) as mock_send:
        await send_digests(session, "fake_token", "daily")
        mock_send.assert_called_once()
        await session.refresh(sub)
        assert sub.last_sent_at is not None

@pytest.mark.asyncio
async def test_send_weekly_digest(session, redis_mock):
    user = User(id=4, chat_id=999)
    item = Item(id=4, app_id=730, market_hash_name="WeeklyItem")
    session.add_all([user, item])
    await session.commit()

    week_ago = date.today() - timedelta(days=7)
    session.add(ItemDailyStats(item_id=item.id, date=week_ago, price=200.0, volume=50))
    snap = ItemSnapshot(
        item_id=item.id,
        median_price=220.0,
        trend_direction="up"
    )
    session.add(snap)
    await session.commit()

    sub = Subscription(
        user_id=user.id,
        item_id=item.id,
        frequency="weekly",
        active=True
    )
    session.add(sub)
    await session.commit()

    with patch('app.services.notifier.send_telegram_message', new_callable=AsyncMock) as mock_send:
        await send_digests(session, "fake_token", "weekly")
        mock_send.assert_called_once()
        await session.refresh(sub)
        assert sub.last_sent_at is not None