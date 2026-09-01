import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.base import async_session
from app.services.steam_client import SteamClient
from app.services.collector import update_snapshots, sync_daily_history
from app.services.notifier import check_price_alerts, send_digests
from app.config import settings
import app.state as state

logger = logging.getLogger(__name__)

async def init_scheduler(redis_client, steam_client: SteamClient):
    scheduler = AsyncIOScheduler()

    async def update_snapshots_job():
        async with async_session() as session:
            await update_snapshots(session, steam_client, settings.APP_ID)

    async def check_alerts_job():
        async with async_session() as session:
            await check_price_alerts(session, settings.BOT_TOKEN)

    async def daily_digest():
        async with async_session() as session:
            await send_digests(session, settings.BOT_TOKEN, "daily")

    async def weekly_digest():
        async with async_session() as session:
            await send_digests(session, settings.BOT_TOKEN, "weekly")

    async def history_sync_job():
        async with async_session() as session:
            await sync_daily_history(session, steam_client, settings.APP_ID)

    scheduler.add_job(update_snapshots_job, 'interval', minutes=30, id='update_snapshots')
    scheduler.add_job(check_alerts_job, 'interval', minutes=30, id='check_alerts')
    scheduler.add_job(daily_digest, 'cron', hour=10, minute=0, id='daily_digest')
    scheduler.add_job(weekly_digest, 'cron', day_of_week='mon', hour=10, minute=0, id='weekly_digest')
    scheduler.add_job(history_sync_job, 'cron', hour=2, minute=0, id='history_sync')

    scheduler.start()
    logger.info("Scheduler started")


async def shutdown_scheduler():
    # Здесь можно остановить scheduler, если он глобальный
    pass