import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Update, WebhookInfo
from fastapi import FastAPI, Request

import app.bot.dispatcher as bot_module
from app import state
from app.bot.cleanup import CleanupManager
from app.config import settings
from app.scheduler.jobs import init_scheduler, shutdown_scheduler
from app.services.steam.factory import create_steam_provider
from app.services.steam_client import SteamClient
from app.utils.retry import retry_async, retry_forever

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    r = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    state.redis_client = r
    logger.info("Redis connected")

    provider = create_steam_provider(r)
    await provider.initialize()
    steam_client = SteamClient(provider)
    state.steam_client = steam_client
    logger.info("Steam client initialized")

    cleanup_manager = CleanupManager(r)
    state.cleanup_manager = cleanup_manager
    logger.info("Cleanup manager initialized")

    await init_scheduler(r, steam_client)

    webhook_url = f"{settings.WEBHOOK_URL}/webhook"

    async def set_webhook():
        await bot_module.bot.set_webhook(
            url=webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        info: WebhookInfo = await bot_module.bot.get_webhook_info()
        if info.url != webhook_url:
            raise RuntimeError(f"Webhook not set correctly: {info.url}")

    await retry_forever(
        set_webhook,
        delay=3.0,
        backoff=2.0,
        exceptions=(TelegramNetworkError, RuntimeError),
    )
    logger.info(f"Webhook set successfully to {webhook_url}")

    yield

    async def delete_webhook():
        await bot_module.bot.delete_webhook()

    try:
        await retry_async(delete_webhook, retries=3, delay=2.0)
    except Exception as e:  # noqa: BLE001 -- must catch all to continue shutdown
        logger.warning(f"Failed to delete webhook: {e}")

    try:
        await shutdown_scheduler()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to shutdown scheduler: {e}")

    try:
        await steam_client.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to close Steam client: {e}")

    try:
        await r.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to close Redis: {e}")

    try:
        await bot_module.bot.session.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to close bot session: {e}")

    logger.info("Application stopped")


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.WEBHOOK_SECRET:
        return {"error": "Forbidden"}, 403
    try:
        data = await request.json()
        update = Update(**data)
        await bot_module.dp.feed_update(bot_module.bot, update)
    except Exception:
        logger.exception("Webhook processing failed")
        # Возвращаем 200 OK, чтобы Telegram не считал запрос неудачным и не спамил
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
