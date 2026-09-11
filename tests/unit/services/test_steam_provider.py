from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from aiosteampy.session.exceptions import SteamError
from aiosteampy.transport.exceptions import NetworkError

from app.services.steam.provider import SteamProvider
from app.services.steam.session_manager import SessionManager


@pytest.fixture
def provider():
    provider = object.__new__(SteamProvider)

    provider._session_manager = MagicMock(spec=SessionManager)
    provider._session = MagicMock()
    provider._client = MagicMock()
    provider._public_client = MagicMock()
    provider._public_client.market.get_price_overview = AsyncMock()
    provider._fallback_country = "RU"
    provider._fallback_currency = 5
    return provider


@pytest.mark.asyncio
async def test_initialize(provider):
    provider._session_manager.get_session = AsyncMock()
    provider._session_manager.get_session.return_value = MagicMock()

    await provider.initialize()

    assert provider._session is not None
    assert provider._client is not None


@pytest.mark.asyncio
async def test_get_price_overview_success(provider):
    # Настроим мок публичного клиента
    provider._public_client = MagicMock()
    provider._public_client.market.get_price_overview = AsyncMock()
    overview = MagicMock()
    overview.lowest_price = 123  # 1.23 в копейках
    overview.median_price = 234
    overview.volume = 100
    provider._public_client.market.get_price_overview.return_value = overview

    # Мокаем retry_async, чтобы просто выполнить функцию
    with patch(
        "app.services.steam.provider.retry_async", new=lambda func, *a, **k: func()
    ):
        data = await provider.get_price_overview(730, "AK-47")

    assert data["success"] is True
    assert data["lowest_price"] == "1.23"
    assert data["median_price"] == "2.34"


@pytest.mark.asyncio
async def test_get_price_overview_keyerror_fallback(provider):
    # Симулируем KeyError при обращении к атрибутам
    provider._public_client = MagicMock()
    provider._public_client.market.get_price_overview = AsyncMock()
    provider._public_client.market.get_price_overview.return_value = MagicMock(
        spec=[]
    )  # вызовет KeyError при обращении к lowest_price?
    # Вместо этого проще замокать retry_async, чтобы бросить KeyError
    with patch("app.services.steam.provider.retry_async", side_effect=KeyError):
        # Мокаем fallback
        provider._get_price_overview_fallback = AsyncMock(
            return_value={"success": True, "lowest_price": "$1.00"}
        )
        data = await provider.get_price_overview(730, "AK-47")

    assert data["success"] is True
    provider._get_price_overview_fallback.assert_called_once()


@pytest.mark.asyncio
async def test_get_price_history(provider):
    provider.ensure_authenticated = AsyncMock(return_value=True)
    provider._client = MagicMock()
    provider._client.market.get_price_history = AsyncMock()
    entry = MagicMock()
    entry.date = MagicMock()
    entry.date.strftime.return_value = "Jan 01 2026 01: +0"
    entry.price_raw = 1.23
    entry.daily_volume = 100
    provider._client.market.get_price_history.return_value = [entry]

    with patch(
        "app.services.steam.provider.retry_async", new=lambda func, *a, **k: func()
    ):
        history = await provider.get_price_history(730, "AK-47")

    assert len(history) == 1
    assert history[0][1] == 1.23


@pytest.mark.asyncio
async def test_ensure_authenticated_valid_cookies(provider):
    provider._session = MagicMock(cookies_are_valid=True)
    result = await provider.ensure_authenticated()
    assert result is True


@pytest.mark.asyncio
async def test_ensure_authenticated_invalid_refresh_success(provider):
    provider._session = MagicMock(cookies_are_valid=False)
    provider._session.refresh_access_token = AsyncMock()
    provider._session.obtain_cookies = AsyncMock()
    # После обновления cookies_are_valid станет True
    provider._session.cookies_are_valid = True
    result = await provider.ensure_authenticated()
    assert result is True


@pytest.mark.asyncio
async def test_ensure_authenticated_refresh_fails_create_new(provider):
    provider._session = MagicMock(cookies_are_valid=False)
    provider._session.refresh_access_token = AsyncMock(
        side_effect=NetworkError("refresh failed")
    )
    provider._session_manager._create_new_session = AsyncMock()
    provider._session_manager.get_session = AsyncMock(
        return_value=MagicMock(cookies_are_valid=True)
    )
    result = await provider.ensure_authenticated()
    assert result is True
    provider._session_manager._create_new_session.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_authenticated_total_failure(provider):
    provider._session = MagicMock(cookies_are_valid=False)
    provider._session.refresh_access_token = AsyncMock(
        side_effect=NetworkError("refresh failed")
    )
    provider._session_manager._create_new_session = AsyncMock(
        side_effect=SteamError("create fail")
    )
    result = await provider.ensure_authenticated()
    assert result is False


@pytest.mark.asyncio
async def test_get_inventory_success(provider):
    provider.ensure_authenticated = AsyncMock(return_value=True)
    provider._client = MagicMock()
    provider._client.inventory.get_user_inventory = AsyncMock()
    item = MagicMock()
    item.asset_id = 1
    item.description.class_id = 111
    item.description.instance_id = 222
    item.description.market_hash_name = "Item A"
    provider._client.inventory.get_user_inventory.return_value.items = [item]

    with patch(
        "app.services.steam.provider.retry_async", new=lambda func, *a, **k: func()
    ):
        data = await provider.get_inventory(123456, 730)

    assert data["success"] is True
    assert "rgInventory" in data
    assert data["rgDescriptions"]["111_222"]["market_hash_name"] == "Item A"


@pytest.mark.asyncio
async def test_get_inventory_authentication_failure(provider):
    provider.ensure_authenticated = AsyncMock(return_value=False)
    data = await provider.get_inventory(123456, 730)
    assert data == {"success": False}


@pytest.mark.asyncio
async def test_get_inventory_empty(provider):
    provider.ensure_authenticated = AsyncMock(return_value=True)
    provider._client = MagicMock()
    provider._client.inventory.get_user_inventory = AsyncMock()
    provider._client.inventory.get_user_inventory.return_value.items = []

    with patch(
        "app.services.steam.provider.retry_async", new=lambda func, *a, **k: func()
    ):
        data = await provider.get_inventory(123456, 730)

    assert data["success"] is True
    assert data["rgInventory"] == {}
    assert data["rgDescriptions"] == {}


@pytest.mark.asyncio
async def test_close(provider):
    provider._client = AsyncMock()
    provider._public_client = AsyncMock()
    provider._session_manager = AsyncMock()

    await provider.close()

    provider._client.transport.close.assert_called_once()
    provider._public_client.transport.close.assert_called_once()
    provider._session_manager.close.assert_called_once()


@pytest.mark.asyncio
@respx.mock
async def test_get_price_overview_fallback_success(provider):
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


@pytest.mark.asyncio
@respx.mock
async def test_get_price_overview_fallback_http_error(provider):
    respx.get("https://steamcommunity.com/market/priceoverview/").mock(
        return_value=httpx.Response(500)
    )
    data = await provider._get_price_overview_fallback(730, "AK-47")
    assert data == {"success": False}


@pytest.mark.asyncio
@respx.mock
async def test_get_price_overview_fallback_api_failure(provider):
    respx.get("https://steamcommunity.com/market/priceoverview/").mock(
        return_value=httpx.Response(200, json={"success": False})
    )
    data = await provider._get_price_overview_fallback(730, "AK-47")
    assert data == {"success": False}


@pytest.mark.asyncio
async def test_get_price_history_auth_failure(provider):
    provider.ensure_authenticated = AsyncMock(return_value=False)
    history = await provider.get_price_history(730, "AK-47")
    assert history == []


@pytest.mark.asyncio
async def test_get_price_history_exception(provider):
    provider.ensure_authenticated = AsyncMock(return_value=True)
    provider._client = MagicMock()

    with patch(
        "app.services.steam.provider.retry_async",
        side_effect=RuntimeError("network error"),
    ):
        history = await provider.get_price_history(730, "AK-47")

    assert history == []


@pytest.mark.asyncio
async def test_get_inventory_item_processing_error(provider):
    """Ошибка на одном предмете инвентаря → success=False."""
    provider.ensure_authenticated = AsyncMock(return_value=True)
    provider._client = MagicMock()

    bad_item = MagicMock()
    # Обращение к asset_id бросит ошибку
    type(bad_item).asset_id = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("bad"))
    )
    provider._client.inventory.get_user_inventory = AsyncMock()
    provider._client.inventory.get_user_inventory.return_value.items = [bad_item]

    with patch("app.services.steam.provider.retry_async", new=lambda f, *a, **k: f()):
        data = await provider.get_inventory(123456, 730)

    assert data["success"] is False


@pytest.mark.asyncio
async def test_get_inventory_network_error(provider):
    provider.ensure_authenticated = AsyncMock(return_value=True)
    provider._client = MagicMock()
    provider._client.inventory.get_user_inventory = AsyncMock()

    with patch(
        "app.services.steam.provider.retry_async",
        side_effect=NetworkError("no connection"),
    ):
        data = await provider.get_inventory(123456, 730)

    assert data["success"] is False


@pytest.mark.asyncio
async def test_close_when_client_is_none(provider):
    provider._client = None
    provider._public_client = None
    provider._session = None
    # Не должно бросать
    await provider.close()


@pytest.mark.asyncio
async def test_ensure_authenticated_no_session(provider):
    """Если _session = None, переходим к созданию новой."""
    provider._session = None
    provider._session_manager._create_new_session = AsyncMock()
    provider._session_manager.get_session = AsyncMock(
        return_value=MagicMock(cookies_are_valid=True)
    )
    result = await provider.ensure_authenticated()
    assert result is True
    provider._session_manager._create_new_session.assert_called_once()
