import pytest
from unittest.mock import AsyncMock, patch
from app.utils.retry import retry_async, retry_forever

@pytest.mark.asyncio
async def test_retry_async_success_first_try():
    func = AsyncMock(return_value="ok")
    result = await retry_async(func, retries=3)
    assert result == "ok"
    func.assert_called_once()

@pytest.mark.asyncio
async def test_retry_async_success_after_failures():
    func = AsyncMock(side_effect=[ValueError, ValueError, "ok"])
    with patch('asyncio.sleep', return_value=None) as mock_sleep:
        result = await retry_async(func, retries=3, delay=0.1)
    assert result == "ok"
    assert func.call_count == 3
    assert mock_sleep.call_count == 2

@pytest.mark.asyncio
async def test_retry_async_all_failures():
    func = AsyncMock(side_effect=ValueError)
    with patch('asyncio.sleep', return_value=None):
        with pytest.raises(ValueError):
            await retry_async(func, retries=3, delay=0.1)
    assert func.call_count == 3

@pytest.mark.asyncio
async def test_retry_forever_success_after_failures():
    func = AsyncMock(side_effect=[ValueError, "ok"])
    with patch('asyncio.sleep', return_value=None):
        result = await retry_forever(func, delay=0.1)
    assert result == "ok"