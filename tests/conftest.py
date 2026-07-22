import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text
from app.db.base import Base
from app.config import settings
from unittest.mock import AsyncMock, patch
from app.db.models import User, Item, UserTrackedItem, ItemDailyStats, ItemSnapshot, Subscription, PriceAlert

TEST_DATABASE_URL = f"postgresql+asyncpg://test_user:test_pass@{settings.DB_HOST}:5432/test_db"

@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def session(test_engine):
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()
        # Очистка всех таблиц после теста (порядок важен из-за внешних ключей)
        tables = [UserTrackedItem, PriceAlert, Subscription, ItemSnapshot, ItemDailyStats, Item, User]
        for table in tables:
            await session.execute(text(f"TRUNCATE TABLE {table.__tablename__} RESTART IDENTITY CASCADE"))
        await session.commit()

@pytest.fixture
def redis_mock():
    with patch("redis.asyncio.from_url") as mock_redis:
        mock_redis.return_value = AsyncMock()
        yield mock_redis

@pytest.fixture
def steam_client_mock():
    with patch("app.services.steam_client.SteamClient") as mock:
        client_instance = AsyncMock()
        mock.return_value = client_instance
        yield client_instance