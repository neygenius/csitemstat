from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.db.models import (
    Item,
    ItemDailyStats,
    ItemSnapshot,
    User,
    UserTrackedItem,
)
from app.services.collector import (
    sync_daily_history,
    update_single_item_snapshot,
    update_snapshots,
)


@pytest.fixture
def mock_steam_client():
    client = AsyncMock()
    client.get_price_overview = AsyncMock(
        return_value={
            "success": True,
            "lowest_price": "$5.00",
            "median_price": "$6.50",
            "volume": "200",
        }
    )
    client.get_price_history = AsyncMock(return_value=[])
    return client


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_update_snapshots_creates_snapshot_and_daily_stats(
    session, mock_steam_client, redis_client
):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47", is_tracked=True)
    session.add(item)
    await session.commit()

    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch("app.state.redis_client", redis_client),
    ):
        await update_snapshots(session, mock_steam_client, app_id=730)

    snapshot = await session.get(ItemSnapshot, item.id)
    assert snapshot is not None
    assert float(snapshot.median_price) == 6.5
    assert float(snapshot.lowest_price) == 5.0
    assert snapshot.volume_24h == 200

    today = datetime.now(timezone.utc).date()
    stat = await session.get(ItemDailyStats, (item.id, today))
    assert stat is not None
    assert float(stat.price) == 6.5
    assert stat.volume == 200


async def test_update_snapshots_updates_existing_records(
    session, mock_steam_client, redis_client
):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47", is_tracked=True)
    session.add(item)
    await session.commit()

    today = datetime.now(timezone.utc).date()
    session.add(
        ItemSnapshot(item_id=item.id, lowest_price=1, median_price=1, volume_24h=1)
    )
    session.add(ItemDailyStats(item_id=item.id, date=today, price=1, volume=1))
    await session.commit()

    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch("app.state.redis_client", redis_client),
    ):
        await update_snapshots(session, mock_steam_client, app_id=730)

    # Дубликаты не создаются — записи обновлены
    assert await _count(session, ItemSnapshot) == 1
    assert await _count(session, ItemDailyStats) == 1

    snapshot = await session.get(ItemSnapshot, item.id)
    assert float(snapshot.median_price) == 6.5


async def test_update_snapshots_skips_untracked_items(
    session, mock_steam_client, redis_client
):
    """is_tracked=False и нет UserTrackedItem → предмет не обрабатывается."""
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47", is_tracked=False)
    session.add(item)
    await session.commit()

    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch("app.state.redis_client", redis_client),
    ):
        await update_snapshots(session, mock_steam_client, app_id=730)

    assert await _count(session, ItemSnapshot) == 0
    assert mock_steam_client.get_price_overview.await_count == 0


async def test_update_snapshots_picks_up_user_tracked_item(
    session, mock_steam_client, redis_client
):
    """is_tracked=False, но есть UserTrackedItem → предмет обрабатывается."""
    user = User(id=1, chat_id=1)
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47", is_tracked=False)
    session.add_all([user, item])
    await session.commit()
    session.add(UserTrackedItem(user_id=user.id, item_id=item.id))
    await session.commit()

    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch("app.state.redis_client", redis_client),
    ):
        await update_snapshots(session, mock_steam_client, app_id=730)

    assert await _count(session, ItemSnapshot) == 1


async def test_update_snapshots_skips_when_steam_fails(session, redis_client):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47", is_tracked=True)
    session.add(item)
    await session.commit()

    failing = AsyncMock()
    failing.get_price_overview = AsyncMock(return_value={"success": False})

    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch("app.state.redis_client", redis_client),
    ):
        await update_snapshots(session, failing, app_id=730)

    assert await _count(session, ItemSnapshot) == 0
    assert await _count(session, ItemDailyStats) == 0


async def test_update_single_item_snapshot_rolls_back_on_error(session, redis_client):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47")
    session.add(item)
    await session.commit()

    failing = AsyncMock()
    failing.get_price_overview = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch("app.state.redis_client", redis_client),
    ):
        result = await update_single_item_snapshot(session, failing, item)

    assert result is False
    # Ничего не записано — rollback сработал
    assert await _count(session, ItemSnapshot) == 0


async def test_sync_daily_history_runs_without_error(session, redis_client):
    item = Item(app_id=730, market_hash_name="AK-47", name="AK-47", is_tracked=True)
    session.add(item)
    await session.commit()

    client = AsyncMock()
    client.get_price_history = AsyncMock(
        return_value=[
            ["Jul 20 2026 01: +0", 10.0, "100"],
            ["Jul 21 2026 01: +0", 11.0, "150"],
        ]
    )

    with patch("app.state.redis_client", redis_client):
        await sync_daily_history(session, client, app_id=730)

    # Smoke-check: не падает и что-то пишет в дневную статистику
    assert await _count(session, ItemDailyStats) >= 1
