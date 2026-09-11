from __future__ import annotations

import os
from collections.abc import AsyncIterator, Generator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from app.db.base import Base


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """PostgreSQL 15, поднимается один раз на всю сессию."""
    container = PostgresContainer(
        image="postgres:15",
        username="test_user",
        password="test_pass",
        dbname="test_db",
        driver="asyncpg",
    )
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, None, None]:
    container = RedisContainer(image="redis:7-alpine")
    container.start()
    yield container
    container.stop()


@pytest_asyncio.fixture(scope="session")
async def db_engine(postgres_container: PostgresContainer):
    url = postgres_container.get_connection_url()
    engine = create_async_engine(
        url, echo=False, poolclass=NullPool, pool_pre_ping=True
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


_TRUNCATE_ORDER = [
    "user_tracked_items",
    "price_alerts",
    "subscriptions",
    "item_snapshot",
    "item_daily_stats",
    "item_hourly_stats",
    "items",
    "users",
]


@pytest_asyncio.fixture
async def session(db_engine) -> AsyncIterator[AsyncSession]:
    """AsyncSession с автoочисткой таблиц после теста."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as s:
        yield s

        await s.rollback()
        await s.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(_TRUNCATE_ORDER)
                + " RESTART IDENTITY CASCADE"
            )
        )
        await s.commit()


@pytest_asyncio.fixture
async def redis_client(
    redis_container: RedisContainer,
) -> AsyncIterator[aioredis.Redis]:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client = aioredis.from_url(
        f"redis://{host}:{port}/0",
        encoding="utf-8",
        decode_responses=False,
    )
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture(autouse=True, scope="session")
def _set_test_env(postgres_container, redis_container):
    """Переопределяем переменные окружения на реальные порты контейнеров.

    Полезно, если какие-то модули читают settings на этапе импорта.
    """
    os.environ["DB_HOST"] = postgres_container.get_container_host_ip()
    os.environ["DB_PORT"] = str(postgres_container.get_exposed_port(5432))
    os.environ["DB_USER"] = "test_user"
    os.environ["DB_PASSWORD"] = "test_pass"
    os.environ["DB_NAME"] = "test_db"

    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)
    os.environ["REDIS_URL"] = f"redis://{redis_host}:{redis_port}/0"
    yield
