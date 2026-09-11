from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport

from app.config import settings
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_webhook_rejects_bad_secret(client):
    resp = await client.post(
        "/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert resp.status_code == 403


async def test_webhook_accepts_valid_secret(client):
    with patch(
        "app.main.bot_module.dp.feed_update", new_callable=AsyncMock
    ) as mock_feed:
        resp = await client.post(
            "/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": settings.WEBHOOK_SECRET},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    mock_feed.assert_awaited_once()


async def test_webhook_handles_invalid_json(client):
    """Невалидный JSON логируется, но клиенту возвращается 200."""
    with patch("app.main.bot_module.dp.feed_update", new_callable=AsyncMock):
        resp = await client.post(
            "/webhook",
            content=b"not a json",
            headers={
                "X-Telegram-Bot-Api-Secret-Token": settings.WEBHOOK_SECRET,
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 200
