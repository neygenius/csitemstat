import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta, date
from app.services.notifier import check_price_alerts, send_digests
from app.db.models import PriceAlert, ItemSnapshot, Subscription, User, Item

@pytest.mark.asyncio
async def test_check_price_alerts_triggers(mock_session, mock_send_telegram_message):
    # Arrange
    alert = PriceAlert(id=1, user_id=1, item_id=1, percent_change=10.0, period="24h", active=True)
    snapshot = ItemSnapshot(item_id=1, median_price=120.0, price_24h_ago=100.0)
    user = User(id=1, chat_id=123)
    item = Item(id=1, market_hash_name="TestItem")
    
    mock_session.execute.return_value.scalars.return_value.all.return_value = [alert]
    mock_session.get = AsyncMock(side_effect=lambda model, pk: {
        (ItemSnapshot, 1): snapshot,
        (User, 1): user,
        (Item, 1): item,
    }.get((model, pk)))
    
    # Act
    await check_price_alerts(mock_session, "fake_token")
    
    # Assert
    mock_send_telegram_message.assert_called_once()
    assert alert.last_triggered_at is not None
    mock_session.commit.assert_called_once()

@pytest.mark.asyncio
async def test_check_price_alerts_no_trigger_small_change(mock_session, mock_send_telegram_message):
    alert = PriceAlert(id=1, user_id=1, item_id=1, percent_change=50.0, period="24h", active=True)
    snapshot = ItemSnapshot(item_id=1, median_price=101.0, price_24h_ago=100.0)
    
    mock_session.execute.return_value.scalars.return_value.all.return_value = [alert]
    mock_session.get = AsyncMock(return_value=snapshot)
    
    await check_price_alerts(mock_session, "fake_token")
    
    mock_send_telegram_message.assert_not_called()

@pytest.mark.asyncio
async def test_check_price_alerts_cooldown(mock_session, mock_send_telegram_message):
    alert = PriceAlert(id=1, user_id=1, item_id=1, percent_change=10.0, period="24h", active=True,
                       last_triggered_at=datetime.now(timezone.utc) - timedelta(minutes=30))
    snapshot = ItemSnapshot(item_id=1, median_price=110.0, price_24h_ago=100.0)
    
    mock_session.execute.return_value.scalars.return_value.all.return_value = [alert]
    mock_session.get = AsyncMock(return_value=snapshot)
    
    await check_price_alerts(mock_session, "fake_token")
    
    mock_send_telegram_message.assert_not_called()

@pytest.mark.asyncio
async def test_send_daily_digest(mock_session, mock_send_telegram_message):
    sub = Subscription(id=1, user_id=1, item_id=1, frequency="daily", active=True)
    snapshot = ItemSnapshot(item_id=1, median_price=150.0, price_24h_ago=140.0, trend_direction="up")
    user = User(id=1, chat_id=789)
    item = Item(id=1, market_hash_name="DailyItem")
    
    mock_session.execute.return_value.scalars.return_value.all.return_value = [sub]
    mock_session.get = AsyncMock(side_effect=lambda model, pk: {
        (ItemSnapshot, 1): snapshot,
        (User, 1): user,
        (Item, 1): item,
    }.get((model, pk)))
    
    await send_digests(mock_session, "fake_token", "daily")
    
    mock_send_telegram_message.assert_called_once()
    assert sub.last_sent_at is not None

@pytest.mark.asyncio
async def test_check_price_alerts_weekly(mock_session, mock_send_telegram_message):
    alert = PriceAlert(id=1, user_id=1, item_id=1, percent_change=10.0, period="weekly", active=True)
    snapshot = ItemSnapshot(item_id=1, median_price=110.0, price_24h_ago=None)
    user = User(id=1, chat_id=123)
    item = Item(id=1, market_hash_name="TestItem")
    
    mock_session.execute.return_value.scalars.return_value.all.return_value = [alert]
    mock_session.get = AsyncMock(side_effect=lambda model, pk: {
        (ItemSnapshot, 1): snapshot,
        (User, 1): user,
        (Item, 1): item,
    }.get((model, pk)))
    # Для weekly старый цена получается через execute -> scalar_one_or_none
    mock_session.execute.return_value.scalar_one_or_none.return_value = 100.0
    
    await check_price_alerts(mock_session, "token")
    mock_send_telegram_message.assert_called_once()

@pytest.mark.asyncio
async def test_check_price_alerts_old_price_zero(mock_session, mock_send_telegram_message):
    alert = PriceAlert(id=1, user_id=1, item_id=1, percent_change=10.0, period="24h", active=True)
    snapshot = ItemSnapshot(item_id=1, median_price=110.0, price_24h_ago=0.0)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [alert]
    mock_session.get = AsyncMock(return_value=snapshot)
    
    await check_price_alerts(mock_session, "token")
    mock_send_telegram_message.assert_not_called()

@pytest.mark.asyncio
async def test_check_price_alerts_inactive_alert(mock_session, mock_send_telegram_message):
    alert = PriceAlert(id=1, user_id=1, item_id=1, percent_change=10.0, period="24h", active=False)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [alert]
    
    await check_price_alerts(mock_session, "token")
    mock_send_telegram_message.assert_not_called()

@pytest.mark.asyncio
async def test_send_digests_weekly(mock_session, mock_send_telegram_message):
    sub = Subscription(id=1, user_id=1, item_id=1, frequency="weekly", active=True)
    snapshot = ItemSnapshot(item_id=1, median_price=150.0, price_24h_ago=None, trend_direction="up")
    user = User(id=1, chat_id=789)
    item = Item(id=1, market_hash_name="WeeklyItem")
    
    mock_session.execute.return_value.scalars.return_value.all.return_value = [sub]
    mock_session.get = AsyncMock(side_effect=lambda model, pk: {
        (ItemSnapshot, 1): snapshot,
        (User, 1): user,
        (Item, 1): item,
    }.get((model, pk)))
    # Для weekly поиск цены через execute -> scalar_one_or_none
    mock_session.execute.return_value.scalar_one_or_none.return_value = 140.0
    
    await send_digests(mock_session, "token", "weekly")
    mock_send_telegram_message.assert_called_once()
    assert sub.last_sent_at is not None