from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Item, ItemDailyStats, ItemHourlyStats, ItemSnapshot
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


@pytest.mark.asyncio
async def test_update_snapshots_handles_item_exception(
    mock_session, mock_steam_client, mock_redis
):
    """Ошибка на одном предмете не должна прерывать обработку остальных."""
    item1 = Item(id=1, app_id=730, market_hash_name="GoodItem", is_tracked=True)
    item2 = Item(id=2, app_id=730, market_hash_name="BadItem", is_tracked=True)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [
        item1,
        item2,
    ]

    async def fake_overview(app_id, name):
        if name == "BadItem":
            raise RuntimeError("Steam is down")
        return {
            "success": True,
            "lowest_price": "$1.00",
            "median_price": "$2.00",
            "volume": "10",
        }

    mock_steam_client.get_price_overview = AsyncMock(side_effect=fake_overview)
    mock_session.scalar = AsyncMock(return_value=0)
    mock_session.get = AsyncMock(return_value=None)

    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch(
            "app.services.collector.compute_trend",
            new_callable=AsyncMock,
            return_value=(0.0, "stable"),
        ),
        patch(
            "app.services.collector.invalidate_price_chart_cache",
            new_callable=AsyncMock,
        ),
        patch("app.state.redis_client", mock_redis),
    ):
        await update_snapshots(mock_session, mock_steam_client, 730)

    # Оба предмета были обработаны, ошибка на втором не прервала цикл
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_update_snapshots_empty_list(mock_session, mock_steam_client, mock_redis):
    mock_session.execute.return_value.scalars.return_value.all.return_value = []
    with patch("app.state.redis_client", mock_redis):
        await update_snapshots(mock_session, mock_steam_client, 730)
    mock_steam_client._provider.get_price_overview.assert_not_called()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_snapshots_volume_with_garbage_chars(
    mock_session, mock_steam_client, mock_redis
):
    """Volume вида '1,234,567' должен корректно очищаться."""
    item = Item(id=1, app_id=730, market_hash_name="Item", is_tracked=True)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [item]
    mock_session.scalar = AsyncMock(return_value=0)
    mock_session.get = AsyncMock(return_value=None)
    mock_steam_client.get_price_overview = AsyncMock(
        return_value={
            "success": True,
            "lowest_price": "$1.00",
            "median_price": "$2.00",
            "volume": "1,234,567",
        }
    )
    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch(
            "app.services.collector.compute_trend",
            new_callable=AsyncMock,
            return_value=(0.0, "stable"),
        ),
        patch(
            "app.services.collector.invalidate_price_chart_cache",
            new_callable=AsyncMock,
        ),
        patch("app.state.redis_client", mock_redis),
    ):
        await update_snapshots(mock_session, mock_steam_client, 730)

    # Проверяем, что volume распарсен корректно (в ItemSnapshot где-то сохранён)
    saved_args = [call.args[0] for call in mock_session.add.call_args_list]
    snapshot = next(obj for obj in saved_args if isinstance(obj, ItemSnapshot))
    assert snapshot.volume_24h == 1234567


@pytest.mark.asyncio
async def test_sync_daily_history_handles_exception(
    mock_session, mock_steam_client, mock_redis
):
    item = Item(id=1, app_id=730, market_hash_name="Item", is_tracked=True)
    mock_session.execute.return_value.scalars.return_value.all.return_value = [item]
    mock_session.scalar = AsyncMock(return_value=0)

    with (
        patch(
            "app.services.collector.save_hourly_history",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "app.services.collector.invalidate_price_chart_cache",
            new_callable=AsyncMock,
        ),
        patch("app.state.redis_client", mock_redis),
    ):
        await sync_daily_history(mock_session, mock_steam_client, 730)

    # Несмотря на ошибку, коммит в конце должен быть
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_item_history_invalid_date(mock_session, mock_steam_client):
    """Невалидная дата в ответе Steam должна логироваться и пропускаться."""
    mock_session.scalar = AsyncMock(side_effect=[0, 0])
    mock_steam_client.get_price_history = AsyncMock(
        return_value=[
            ["garbage date", 10.0, "100"],  # не распарсится
            ["Jul 21 2026 01: +0", 11.0, "150"],
        ]
    )
    mock_session.get = AsyncMock(return_value=None)
    item = Item(id=1, app_id=730, market_hash_name="Test")

    await collector.ensure_item_history(mock_session, mock_steam_client, item)

    # Только одна валидная запись добавлена
    assert mock_session.add.call_count == 1


@pytest.mark.asyncio
async def test_ensure_item_history_only_hourly_exists(mock_session, mock_steam_client):
    """Если есть только hourly, но не daily — история догружается."""
    mock_session.scalar = AsyncMock(side_effect=[10, 0])  # hourly есть, daily нет
    mock_steam_client.get_price_history = AsyncMock(return_value=[])
    item = Item(id=1, app_id=730, market_hash_name="Test")

    await collector.ensure_item_history(mock_session, mock_steam_client, item)
    # Запрос к истории был сделан (для догрузки)
    mock_steam_client.get_price_history.assert_called_once()


@pytest.mark.asyncio
async def test_update_single_item_snapshot_rollback_on_exception(
    mock_session, mock_steam_client
):
    item = Item(id=1, app_id=730, market_hash_name="Item")
    mock_steam_client.get_price_overview = AsyncMock(
        return_value={
            "success": True,
            "lowest_price": "$1",
            "median_price": "$2",
            "volume": "10",
        }
    )
    mock_session.get = AsyncMock(return_value=None)
    mock_session.scalar = AsyncMock(return_value=0)

    # compute_trend кидает, чтобы попасть в except-ветку
    with (
        patch("app.services.collector.ensure_item_history", new_callable=AsyncMock),
        patch(
            "app.services.collector.compute_trend",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
    ):
        result = await collector.update_single_item_snapshot(
            mock_session, mock_steam_client, item
        )

    assert result is False
    mock_session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_update_single_item_snapshot_data_none(mock_session, mock_steam_client):
    item = Item(id=1, app_id=730, market_hash_name="Item")
    mock_steam_client.get_price_overview = AsyncMock(return_value=None)
    with patch("app.services.collector.ensure_item_history", new_callable=AsyncMock):
        result = await collector.update_single_item_snapshot(
            mock_session, mock_steam_client, item
        )
    assert result is False
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_get_price_24h_ago_daily_fallback(mock_session):
    """Если часовых нет, берём вчерашнюю дневную."""
    mock_session.execute.return_value.scalar_one_or_none.side_effect = [None, 9.5]
    price = await collector.get_price_24h_ago(mock_session, item_id=1)
    assert price == 9.5


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$1.23 USD", 1.23),
        ("1 234,56", 1234.56),  # пробелы как разделитель тысяч
        ("  1.23  ", 1.23),
        ("abc", 0.0),
    ],
)
def test_parse_steam_price_edge_cases(raw, expected):
    assert collector.parse_steam_price(raw) == expected
