from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import (
    Item,
    ItemDailyStats,
    ItemSnapshot,
    PriceAlert,
    Subscription,
    User,
)
from app.services.notifier import check_price_alerts, send_digests

pytestmark = pytest.mark.integration


async def test_check_price_alerts_triggers_and_persists(session):
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(
        ItemSnapshot(
            item_id=item.id,
            median_price=110.0,
            lowest_price=100.0,
            volume_24h=10,
            price_24h_ago=100.0,
        )
    )
    session.add(
        PriceAlert(
            user_id=user.id,
            item_id=item.id,
            percent_change=5.0,
            period="24h",
            active=True,
        )
    )
    await session.commit()

    with patch(
        "app.services.notifier.send_telegram_message", new_callable=AsyncMock
    ) as mock_send:
        await check_price_alerts(session, "token")

    mock_send.assert_awaited_once()

    alert = (await session.execute(select(PriceAlert))).scalar_one()
    assert alert.last_triggered_at is not None


async def test_check_price_alerts_respects_cooldown(session):
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(
        ItemSnapshot(
            item_id=item.id,
            median_price=110.0,
            price_24h_ago=100.0,
        )
    )
    session.add(
        PriceAlert(
            user_id=user.id,
            item_id=item.id,
            percent_change=5.0,
            period="24h",
            active=True,
            last_triggered_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
    )
    await session.commit()

    with patch(
        "app.services.notifier.send_telegram_message", new_callable=AsyncMock
    ) as mock_send:
        await check_price_alerts(session, "token")

    mock_send.assert_not_awaited()


async def test_check_price_alerts_skips_small_change(session):
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(ItemSnapshot(item_id=item.id, median_price=101.0, price_24h_ago=100.0))
    session.add(
        PriceAlert(
            user_id=user.id,
            item_id=item.id,
            percent_change=5.0,
            period="24h",
            active=True,
        )
    )
    await session.commit()

    with patch(
        "app.services.notifier.send_telegram_message", new_callable=AsyncMock
    ) as mock_send:
        await check_price_alerts(session, "token")

    mock_send.assert_not_awaited()


async def test_send_digests_daily_updates_last_sent_at(session):
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(
        ItemSnapshot(
            item_id=item.id,
            median_price=150.0,
            price_24h_ago=140.0,
            trend_direction="up",
        )
    )
    session.add(
        Subscription(
            user_id=user.id,
            item_id=item.id,
            frequency="daily",
            active=True,
        )
    )
    await session.commit()

    with patch(
        "app.services.notifier.send_telegram_message", new_callable=AsyncMock
    ) as mock_send:
        await send_digests(session, "token", "daily")

    mock_send.assert_awaited_once()
    sub = (await session.execute(select(Subscription))).scalar_one()
    assert sub.last_sent_at is not None


async def test_send_digests_only_matching_frequency(session):
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()
    session.add(ItemSnapshot(item_id=item.id, median_price=150.0, price_24h_ago=140.0))
    session.add(
        Subscription(
            user_id=user.id,
            item_id=item.id,
            frequency="weekly",
            active=True,
        )
    )
    await session.commit()

    with patch(
        "app.services.notifier.send_telegram_message", new_callable=AsyncMock
    ) as mock_send:
        await send_digests(session, "token", "daily")

    mock_send.assert_not_awaited()


async def test_send_digests_weekly_uses_daily_stats(session):
    """Weekly-дайджест берёт цену из ItemDailyStats за 7 дней назад."""
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    seven_days_ago = datetime.now(tz=timezone.utc).date() - timedelta(days=7)
    session.add(
        ItemDailyStats(
            item_id=item.id,
            date=seven_days_ago,
            price=140.0,
            volume=50,
        )
    )
    session.add(
        ItemSnapshot(
            item_id=item.id,
            median_price=150.0,
            price_24h_ago=140.0,
            trend_direction="up",
        )
    )
    session.add(
        Subscription(
            user_id=user.id,
            item_id=item.id,
            frequency="weekly",
            active=True,
        )
    )
    await session.commit()

    with patch(
        "app.services.notifier.send_telegram_message", new_callable=AsyncMock
    ) as mock_send:
        await send_digests(session, "token", "weekly")

    mock_send.assert_awaited_once()
    text = mock_send.call_args.args[2]
    # 150 vs 140 → +7.1%
    assert "7.1%" in text
    assert "за неделю" in text


async def test_send_digests_weekly_no_old_stats_gives_na(session):
    """Если нет данных за 7 дней — change_str = 'Н/Д'."""
    user = User(id=1, chat_id=100)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add_all([user, item])
    await session.commit()

    session.add(
        ItemSnapshot(
            item_id=item.id,
            median_price=150.0,
            trend_direction="stable",
        )
    )
    session.add(
        Subscription(
            user_id=user.id,
            item_id=item.id,
            frequency="weekly",
            active=True,
        )
    )
    await session.commit()

    with patch(
        "app.services.notifier.send_telegram_message", new_callable=AsyncMock
    ) as mock_send:
        await send_digests(session, "token", "weekly")

    mock_send.assert_awaited_once()
    assert "Н/Д" in mock_send.call_args.args[2]
