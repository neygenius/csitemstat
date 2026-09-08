from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.messages import send_photo, send_telegram_message


@pytest.mark.asyncio
async def test_send_telegram_message_success():
    with patch("httpx.AsyncClient") as MockClient:
        client = AsyncMock()
        client.post.return_value = MagicMock(status_code=200)
        client.post.return_value.raise_for_status = MagicMock()
        MockClient.return_value.__aenter__.return_value = client
        await send_telegram_message("token", 123, "Hello")
        client.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_telegram_message_retries():
    with (
        patch("httpx.AsyncClient"),
        patch("app.bot.messages.retry_async", new_callable=AsyncMock) as mock_retry,
    ):
        mock_retry.side_effect = Exception("fail")
        await send_telegram_message("token", 123, "Hello")
        mock_retry.assert_called_once()


@pytest.mark.asyncio
async def test_send_photo_success():
    with patch("httpx.AsyncClient") as MockClient:
        client = AsyncMock()
        client.post.return_value = MagicMock(status_code=200)
        MockClient.return_value.__aenter__.return_value = client
        await send_photo("token", 123, b"image bytes", caption="test")
        client.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_photo_retries_on_failure():
    with (
        patch("httpx.AsyncClient"),
        patch("app.bot.messages.retry_async", new_callable=AsyncMock) as mock_retry,
    ):
        mock_retry.side_effect = Exception("fail")
        await send_photo("token", 123, b"image bytes")
        mock_retry.assert_called_once()
