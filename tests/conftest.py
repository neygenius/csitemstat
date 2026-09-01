import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text
from app.db.base import Base
from app.config import settings
from unittest.mock import AsyncMock, patch
from app.db.models import User, Item, UserTrackedItem, ItemDailyStats, ItemSnapshot, Subscription, PriceAlert
from app.services.steam.interface import ISteamProvider

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
def steam_provider_mock():
    mock = AsyncMock(spec=ISteamProvider)
    mock.initialize.return_value = None
    mock.ensure_authenticated.return_value = True
    mock.get_price_overview.return_value = {
        "success": True,
        "lowest_price": "$1.23",
        "median_price": "$2.34",
        "volume": "100"
    }
    mock.get_price_history.return_value = [
        ["Jan 01 2026", 1.23, "100"]
    ]
    mock.get_inventory.return_value = {
        "success": True,
        "rgInventory": {},
        "rgDescriptions": {}
    }
    mock.close.return_value = None
    return mock

@pytest.fixture
def steam_client_mock(steam_provider_mock):
    from app.services.steam_client import SteamClient
    return SteamClient(steam_provider_mock)