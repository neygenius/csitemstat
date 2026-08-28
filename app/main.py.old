import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
import redis.asyncio as redis

from app.config import settings
from app.scheduler.jobs import init_scheduler, shutdown_scheduler
from app.bot.dispatcher import dp, bot, redis_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация Redis
    r = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    redis_client = r
    app.state.redis = r

    # Запуск планировщика (сбор цен, алерты, дайджесты)
    await init_scheduler(r)

    # Удаляем вебхук на случай, если он был установлен ранее
    await bot.delete_webhook(drop_pending_updates=True)
    # Запускаем поллинг в фоновой задаче, чтобы не блокировать uvicorn
    polling_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("Bot polling started")

    yield

    # Завершение: останавливаем поллинг и закрываем соединения
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass
    await shutdown_scheduler()
    await r.close()
    await bot.session.close()
    logger.info("Application stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}