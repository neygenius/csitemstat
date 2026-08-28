import logging
import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from app.config import settings
from app.scheduler.jobs import init_scheduler, shutdown_scheduler
from aiogram.types import Update
import app.bot.dispatcher as bot_module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация Redis
    r = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    bot_module.redis_client = r   # устанавливаем глобальную переменную в dispatcher
    app.state.redis = r
    logger.info("Redis connected")

    await init_scheduler(r)
    
    webhook_url = f"{settings.WEBHOOK_URL}/webhook"
    await bot_module.bot.set_webhook(webhook_url, secret_token=settings.WEBHOOK_SECRET)
    logger.info(f"Webhook set to {webhook_url}")

    yield

    await bot_module.bot.delete_webhook()
    await shutdown_scheduler()
    await r.close()
    await bot_module.bot.session.close()

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
    except Exception as e:
        logger.exception(f"Webhook processing failed: {e}")
        # Возвращаем 200 OK, чтобы Telegram не считал запрос неудачным и не спамил
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "ok"}