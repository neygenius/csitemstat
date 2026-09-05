from typing import Optional

from redis.asyncio.client import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.cleanup import CleanupManager
from app.services.steam_client import SteamClient


redis_client: Redis = None
steam_client: Optional[SteamClient] = None
cleanup_manager: CleanupManager = None
scheduler: Optional[AsyncIOScheduler] = None