from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio.client import Redis

from app.bot.cleanup import CleanupManager
from app.services.steam_client import SteamClient

redis_client: Redis = None
steam_client: SteamClient | None = None
cleanup_manager: CleanupManager = None
scheduler: AsyncIOScheduler | None = None
