from unittest.mock import AsyncMock, patch

import pytest

from app.db.base import get_session


@pytest.mark.asyncio
async def test_get_session_yields_async_session():
    fake_session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=fake_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.db.base.async_session", return_value=ctx):
        gen = get_session()
        session = await gen.__anext__()
        assert session is fake_session

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()


@pytest.mark.asyncio
async def test_get_session_closes_on_exit():
    fake_session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=fake_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.db.base.async_session", return_value=ctx):
        async for _ in get_session():
            pass

    ctx.__aexit__.assert_called_once()
