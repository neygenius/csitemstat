import httpx
import pytest
import respx

from app.services.steam.provider import SteamProvider
from app.services.steam.session_manager import SessionManager


@pytest.fixture
def provider(mocker):
    # Не создаём реальный aiohttp-клиент — он требует running loop при init
    mocker.patch("app.services.steam.provider.SteamPublicClient")
    return SteamProvider(SessionManager(redis_client=None))


@respx.mock
async def test_fallback_success(provider):
    respx.get("https://steamcommunity.com/market/priceoverview/").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "lowest_price": "$1.50",
                "median_price": "$2.00",
                "volume": "42",
            },
        )
    )
    data = await provider._get_price_overview_fallback(730, "AK-47")
    assert data["success"] is True
    assert data["lowest_price"] == "$1.50"
    assert data["volume"] == "42"


@respx.mock
async def test_fallback_http_error(provider):
    respx.get("https://steamcommunity.com/market/priceoverview/").mock(
        return_value=httpx.Response(500)
    )
    data = await provider._get_price_overview_fallback(730, "AK-47")
    assert data == {"success": False}


@respx.mock
async def test_fallback_api_failure(provider):
    respx.get("https://steamcommunity.com/market/priceoverview/").mock(
        return_value=httpx.Response(200, json={"success": False})
    )
    data = await provider._get_price_overview_fallback(730, "AK-47")
    assert data == {"success": False}


@respx.mock
async def test_fallback_passes_correct_params(provider):
    route = respx.get("https://steamcommunity.com/market/priceoverview/").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "lowest_price": "$1",
                "median_price": "$2",
                "volume": "1",
            },
        )
    )
    await provider._get_price_overview_fallback(730, "AK-47")

    assert route.called
    request = route.calls.last.request
    assert request.url.params["appid"] == "730"
    assert request.url.params["market_hash_name"] == "AK-47"
    assert request.url.params["country"] == "RU"
    assert request.url.params["currency"] == "5"
