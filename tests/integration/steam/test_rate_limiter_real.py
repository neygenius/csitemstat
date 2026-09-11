import asyncio
from unittest.mock import AsyncMock, patch

from app.services.steam_client import RateLimiter


async def test_acquire_under_limit_is_fast():
    limiter = RateLimiter(rate=20, period=60.0)
    start = asyncio.get_event_loop().time()
    for _ in range(20):
        await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 0.2  # не должно быть реального ожидания


async def test_acquire_over_limit_sleeps():
    limiter = RateLimiter(rate=2, period=60.0)
    await limiter.acquire()
    await limiter.acquire()

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await limiter.acquire()
    # Токенов больше нет — должен быть вызов sleep
    mock_sleep.assert_awaited()


async def test_tokens_refill_over_time():
    limiter = RateLimiter(rate=2, period=60.0)
    await limiter.acquire()
    await limiter.acquire()
    assert limiter.tokens == 0

    # Имитируем прошествие 30 секунд: обновляем updated_at
    limiter.updated_at -= 30

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await limiter.acquire()
    # Пополнилось ровно 1 токен и сразу израсходовалось — ждать не нужно
    mock_sleep.assert_not_awaited()


async def test_concurrent_acquire_serialized_by_lock():
    """Параллельные вызовы не должны приводить к превышению лимита."""
    limiter = RateLimiter(rate=3, period=60.0)
    sleep_calls = []

    async def fake_sleep(s):
        sleep_calls.append(s)

    with patch("asyncio.sleep", side_effect=fake_sleep):
        await asyncio.gather(*(limiter.acquire() for _ in range(6)))

    # Из 6 вызовов минимум 3 должны были "поспать"
    assert len(sleep_calls) >= 3
