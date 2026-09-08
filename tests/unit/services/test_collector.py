from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Item, ItemDailyStats, ItemHourlyStats
from app.services import collector
from app.services.collector import (
    aggregate_hourly_to_daily,
    get_price_24h_ago,
    parse_steam_price,
    sync_daily_history,
    update_snapshots,
)


@pytest.mark.parametrize(
    "input_price, expected",
    [
        ("$1.23", 1.23),
        ("1,23", 1.23),
        ("$1,234.56", 1234.56),
        ("0", 0.0),
        ("", 0.0),
    ],
)
def test_parse_steam_price(input_price, expected):
    assert parse_steam_price(input_price) == expected


@pytest.mark.asyncio
async def test_update_snapshots_success(mock_session, mock_steam_client, mock_redis):
    item = Item(id=1, app_id=730, market_hash_name="TestItem", is_tracked=True)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [item]
    mock_steam_client.get_price_overview = AsyncMock(
        return_value={
            "success": True,
            "lowest_price": "$5.00",
            "median_price": "$6.50",
            "volume": "200",
        }
    )
    mock_session.get = AsyncMock(return_value=None)

    with (
        patch("app.state.redis_client", mock_redis),
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch(
            "app.services.collector.compute_trend", new_callable=AsyncMock
        ) as mock_trend,
        patch(
            "app.services.collector.invalidate_price_chart_cache",
            new_callable=AsyncMock,
        ) as mock_invalidate,
    ):
        mock_trend.return_value = (0.1, "up")

        await update_snapshots(mock_session, mock_steam_client, 730)

        assert mock_session.add.call_count >= 2
        mock_session.commit.assert_called_once()
        mock_invalidate.assert_called_once_with(mock_redis, item.id)


@pytest.mark.asyncio
async def test_update_snapshots_price_failure(mock_session, mock_steam_client):
    item = Item(id=1, app_id=730, market_hash_name="TestItem", is_tracked=True)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [item]
    mock_steam_client.get_price_overview = AsyncMock(return_value={"success": False})

    await update_snapshots(mock_session, mock_steam_client, 730)

    mock_session.add.assert_not_called()  # ничего не должно добавляться


@pytest.mark.asyncio
async def test_sync_daily_history(mock_session, mock_steam_client, mock_redis):
    item = Item(id=1, app_id=730, market_hash_name="TestItem", is_tracked=True)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [item]
    mock_steam_client.get_price_history = AsyncMock(
        return_value=[
            ["Jul 20 2026 01: +0", 10.0, "123"],
            ["Jul 21 2026 01: +0", 11.0, "150"],
        ]
    )
    mock_session.get = AsyncMock(return_value=None)  # нет существующих записей

    await sync_daily_history(mock_session, mock_steam_client, 730)

    assert mock_session.add.call_count == 2  # добавлены две записи ItemDailyStats
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_aggregate_hourly_to_daily(mock_session):
    hourly_records = [
        ItemHourlyStats(
            item_id=1,
            timestamp=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            price=10.0,
            volume=100,
        ),
        ItemHourlyStats(
            item_id=1,
            timestamp=datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc),
            price=11.0,
            volume=150,
        ),
        ItemHourlyStats(
            item_id=1,
            timestamp=datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc),
            price=12.0,
            volume=200,
        ),
    ]
    mock_session.execute.return_value.scalars.return_value.all.return_value = (
        hourly_records
    )
    mock_session.get.return_value = None  # дневных записей нет

    await aggregate_hourly_to_daily(mock_session, item_id=1)

    assert mock_session.add.call_count == 2  # созданы две дневные записи


@pytest.mark.asyncio
async def test_get_price_24h_ago_hourly(mock_session):
    mock_session.execute.return_value.scalar_one_or_none.return_value = 10.5

    price = await get_price_24h_ago(mock_session, item_id=1)

    assert price == 10.5
    # Проверяем, что был вызван запрос на выборку часовой записи
    assert mock_session.execute.called


@pytest.mark.asyncio
async def test_get_price_24h_ago_daily(mock_session):
    mock_session.execute.return_value.scalar_one_or_none.side_effect = [
        None,
        9.8,
    ]  # часовая -> None, дневная -> 9.8

    price = await get_price_24h_ago(mock_session, item_id=1)

    assert price == 9.8


@pytest.mark.asyncio
async def test_ensure_item_history_existing_data(mock_session, mock_steam_client):
    mock_session.scalar = AsyncMock(
        side_effect=[10, 5]
    )  # hourly_count=10, daily_count=5
    item = Item(id=1, app_id=730, market_hash_name="Test")
    mock_steam_client.get_price_history = AsyncMock()
    await collector.ensure_item_history(mock_session, mock_steam_client, item)
    mock_steam_client.get_price_history.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_item_history_loads_data(mock_session, mock_steam_client):
    mock_session.scalar = AsyncMock(side_effect=[0, 0])  # нет данных
    mock_steam_client.get_price_history = AsyncMock(
        return_value=[
            ["Jul 20 2026 01: +0", 10.0, "100"],
            ["Jul 21 2026 01: +0", 11.0, "150"],
        ]
    )
    mock_session.get = AsyncMock(return_value=None)
    item = Item(id=1, app_id=730, market_hash_name="Test")

    with patch(
        "app.services.collector.aggregate_hourly_to_daily", new_callable=AsyncMock
    ) as mock_aggregate:
        await collector.ensure_item_history(mock_session, mock_steam_client, item)

    assert mock_session.add.call_count >= 2
    mock_session.flush.assert_called_once()
    mock_aggregate.assert_called()


@pytest.mark.asyncio
async def test_save_hourly_history(mock_session, mock_steam_client):
    mock_steam_client.get_price_history = AsyncMock(
        return_value=[
            ["Jul 20 2026 01: +0", 10.0, "100"],
            ["Jul 21 2026 01: +0", 11.0, "150"],
        ]
    )
    mock_session.get = AsyncMock(return_value=None)
    item = Item(id=1, app_id=730, market_hash_name="Test")

    await collector.save_hourly_history(mock_session, mock_steam_client, item, days=30)

    assert mock_session.add.call_count == 2
    assert mock_session.flush.called


@pytest.mark.asyncio
async def test_update_single_item_snapshot_success(mock_session, mock_steam_client):
    item = Item(id=1, app_id=730, market_hash_name="TestItem")
    mock_steam_client.get_price_overview = AsyncMock(
        return_value={
            "success": True,
            "lowest_price": "$5.00",
            "median_price": "$6.50",
            "volume": "200",
        }
    )
    mock_session.get = AsyncMock(return_value=None)
    with patch(
        "app.services.collector.compute_trend", new_callable=AsyncMock
    ) as mock_trend:
        mock_trend.return_value = (0.1, "up")
        result = await collector.update_single_item_snapshot(
            mock_session, mock_steam_client, item
        )
    assert result is True
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_single_item_snapshot_failure(mock_session, mock_steam_client):
    item = Item(id=1, app_id=730, market_hash_name="TestItem")
    mock_steam_client.get_price_overview = AsyncMock(return_value={"success": False})
    result = await collector.update_single_item_snapshot(
        mock_session, mock_steam_client, item
    )
    assert result is False
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_aggregate_hourly_to_daily_update_existing(mock_session):
    # Существующая дневная запись
    day_stat = ItemDailyStats(item_id=1, date=date(2026, 7, 20), price=0, volume=0)
    mock_session.get = AsyncMock(return_value=day_stat)
    hourly_records = [
        ItemHourlyStats(
            item_id=1,
            timestamp=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            price=10.0,
            volume=100,
        ),
        ItemHourlyStats(
            item_id=1,
            timestamp=datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc),
            price=11.0,
            volume=150,
        ),
    ]
    mock_session.execute.return_value.scalars.return_value.all.return_value = (
        hourly_records
    )

    await collector.aggregate_hourly_to_daily(mock_session, item_id=1)

    # Проверяем, что day_stat обновлён
    assert float(day_stat.price) == 10.5  # (10+11)/2
    assert day_stat.volume == 250
    mock_session.add.assert_not_called()  # не создаём новую


@pytest.mark.asyncio
async def test_get_price_24h_ago_none(mock_session):
    mock_session.execute.return_value.scalar_one_or_none.side_effect = [None, None]
    price = await collector.get_price_24h_ago(mock_session, item_id=1)
    assert price is None
