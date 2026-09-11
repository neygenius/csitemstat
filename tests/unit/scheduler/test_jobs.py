from unittest.mock import AsyncMock, MagicMock

import pytest

from app import state
from app.scheduler.jobs import init_scheduler, shutdown_scheduler


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def mock_steam_client():
    return AsyncMock()


@pytest.mark.asyncio
async def test_init_scheduler_adds_five_jobs(mocker):
    mock_scheduler = mocker.patch("app.scheduler.jobs.AsyncIOScheduler").return_value
    mock_scheduler.add_job = MagicMock()
    mock_scheduler.start = MagicMock()

    await init_scheduler(mock_redis, mock_steam_client)

    assert mock_scheduler.add_job.call_count == 5
    calls = mock_scheduler.add_job.call_args_list

    # Проверяем ключевые параметры каждой задачи
    # 1. update_snapshots: interval, minutes=30
    assert calls[0].kwargs["id"] == "update_snapshots"
    assert calls[0].args[1] == "interval"
    assert calls[0].kwargs["minutes"] == 30

    # 2. check_alerts: interval, minutes=30
    assert calls[1].kwargs["id"] == "check_alerts"
    assert calls[1].args[1] == "interval"
    assert calls[1].kwargs["minutes"] == 30

    # 3. daily_digest: cron, hour=10, minute=0
    assert calls[2].kwargs["id"] == "daily_digest"
    assert calls[2].args[1] == "cron"
    assert calls[2].kwargs["hour"] == 10
    assert calls[2].kwargs["minute"] == 0

    # 4. weekly_digest: cron, day_of_week='mon', hour=10, minute=0
    assert calls[3].kwargs["id"] == "weekly_digest"
    assert calls[3].args[1] == "cron"
    assert calls[3].kwargs["day_of_week"] == "mon"
    assert calls[3].kwargs["hour"] == 10
    assert calls[3].kwargs["minute"] == 0

    # 5. history_sync: cron, hour=2, minute=0
    assert calls[4].kwargs["id"] == "history_sync"
    assert calls[4].args[1] == "cron"
    assert calls[4].kwargs["hour"] == 2
    assert calls[4].kwargs["minute"] == 0

    mock_scheduler.start.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_scheduler_with_scheduler(mocker):
    mock_scheduler = MagicMock()
    mocker.patch.object(state, "scheduler", mock_scheduler)

    await shutdown_scheduler()

    mock_scheduler.shutdown.assert_called_once_with(wait=False)


@pytest.mark.asyncio
async def test_shutdown_scheduler_without_scheduler(mocker):
    mocker.patch.object(state, "scheduler", None)

    await shutdown_scheduler()
    # Нет планировщика - не вызывается shutdown (проверка на исключение)


@pytest.mark.asyncio
async def test_jobs_call_services(mocker):
    """Проверяем, что job-функции вызывают сервисы с ожидаемыми аргументами."""
    mock_scheduler = mocker.patch("app.scheduler.jobs.AsyncIOScheduler").return_value
    mock_scheduler.add_job = MagicMock()
    mock_scheduler.start = MagicMock()

    mock_update = mocker.patch(
        "app.scheduler.jobs.update_snapshots", new_callable=AsyncMock
    )
    mock_check = mocker.patch(
        "app.scheduler.jobs.check_price_alerts", new_callable=AsyncMock
    )
    mock_daily = mocker.patch("app.scheduler.jobs.send_digests", new_callable=AsyncMock)
    mock_history = mocker.patch(
        "app.scheduler.jobs.sync_daily_history", new_callable=AsyncMock
    )

    mock_session_ctx = mocker.patch("app.scheduler.jobs.async_session")
    mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

    steam_client = AsyncMock()
    await init_scheduler(AsyncMock(), steam_client)

    # Достаём функции из вызовов add_job и выполняем их
    job_funcs = [call.args[0] for call in mock_scheduler.add_job.call_args_list]
    for func in job_funcs:
        await func()

    mock_update.assert_called_once()
    mock_check.assert_called_once()
    assert mock_daily.call_count == 2  # daily + weekly
    mock_history.assert_called_once()


@pytest.mark.asyncio
async def test_init_scheduler_stores_in_state(mocker):
    mock_scheduler_cls = mocker.patch("app.scheduler.jobs.AsyncIOScheduler")
    mock_scheduler = mock_scheduler_cls.return_value
    mock_scheduler.add_job = MagicMock()
    mock_scheduler.start = MagicMock()

    from app import state

    mocker.patch.object(state, "scheduler", None)

    await init_scheduler(AsyncMock(), AsyncMock())

    assert state.scheduler is mock_scheduler
