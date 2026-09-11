import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosteampy.session import GuardConfirmationRequired
from aiosteampy.transport.exceptions import NetworkError

from app.config import settings
from app.services.steam.session_manager import SessionManager


@pytest.fixture
def session_manager():
    return SessionManager(redis_client=AsyncMock())


@pytest.mark.asyncio
async def test_get_session_existing(session_manager):
    session_manager._session = MagicMock()
    result = await session_manager.get_session()
    assert result == session_manager._session


@pytest.mark.asyncio
async def test_restore_or_create_from_redis(session_manager):
    # Arrange
    session_manager.redis.get = AsyncMock(return_value='{"valid": true}')
    session_manager._session = None
    with patch(
        "app.services.steam.session_manager.SteamSession.deserialize",
        return_value=MagicMock(cookies_are_valid=True),
    ):
        await session_manager._restore_or_create()
    assert session_manager._session is not None


@pytest.mark.asyncio
async def test_create_new_session(session_manager):
    # Arrange
    session_manager.redis = None  # без Redis
    with (
        patch("app.services.steam.session_manager.SteamSession") as MockSession,
        patch(
            "app.services.steam.session_manager.retry_async",
            new=lambda func, *a, **k: func(),
        ),
    ):
        mock_session = MockSession.return_value
        mock_session.with_credentials = AsyncMock()
        mock_session.finalize = AsyncMock()
        mock_session.obtain_cookies = AsyncMock()

        await session_manager._create_new_session()

        assert mock_session.with_credentials.called
        assert mock_session.finalize.called


@pytest.mark.asyncio
async def test_restore_or_create_invalid_cookies_refresh_fails(session_manager):
    session_manager.redis.get = AsyncMock(return_value='{"some": "data"}')
    with patch(
        "app.services.steam.session_manager.SteamSession.deserialize"
    ) as mock_deser:
        mock_session = MagicMock(cookies_are_valid=False)
        mock_session.refresh_access_token = AsyncMock(
            side_effect=NetworkError("refresh failed")
        )
        mock_deser.return_value = mock_session
        with patch.object(
            session_manager, "_create_new_session", new_callable=AsyncMock
        ) as mock_create:
            await session_manager._restore_or_create()
            mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_load_guard_account_file_not_found(
    session_manager, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "STEAM_GUARD_FILE", str(tmp_path / "nofile.maFile"))
    result = session_manager._load_guard_account()
    assert result is None


@pytest.mark.asyncio
async def test_load_guard_account_invalid_json(session_manager, tmp_path, monkeypatch):
    path = tmp_path / "invalid.maFile"
    path.write_text("not json")
    monkeypatch.setattr(settings, "STEAM_GUARD_FILE", str(path))
    result = session_manager._load_guard_account()
    assert result is None


@pytest.mark.asyncio
async def test_create_new_session_with_guard_confirmation(session_manager):
    session_manager.redis = None
    with (
        patch("app.services.steam.session_manager.SteamSession") as MockSession,
        patch(
            "app.services.steam.session_manager.retry_async",
            new=lambda func, *a, **k: func(),
        ),
    ):
        mock_session = MockSession.return_value
        mock_session.with_credentials = AsyncMock(
            side_effect=GuardConfirmationRequired(
                confirmations=[], allowed_guard_types=[]
            )
        )
        mock_session.submit_auth_code = AsyncMock()
        mock_session.finalize = AsyncMock()
        mock_session.obtain_cookies = AsyncMock()

        # Мокаем _load_guard_account, чтобы вернуть объект с shared_secret
        with patch.object(
            session_manager,
            "_load_guard_account",
            return_value=MagicMock(
                shared_secret=MagicMock(
                    generate_auth_code=MagicMock(return_value="ABC")
                )
            ),
        ):
            await session_manager._create_new_session()

        mock_session.submit_auth_code.assert_called_once_with("ABC", "device")


@pytest.mark.asyncio
async def test_get_session_creates_when_none(session_manager):
    session_manager._session = None

    async def fake_restore():
        session_manager._session = MagicMock()

    with patch.object(
        session_manager, "_restore_or_create", side_effect=fake_restore
    ) as mock:
        result = await session_manager.get_session()
        mock.assert_called_once()
        assert result is session_manager._session


@pytest.mark.asyncio
async def test_restore_or_create_successful_refresh(session_manager):
    session_manager.redis.get = AsyncMock(return_value='{"some":"data"}')
    with patch(
        "app.services.steam.session_manager.SteamSession.deserialize"
    ) as mock_deser:
        session = MagicMock()
        session.cookies_are_valid = False
        session.refresh_access_token = AsyncMock()
        session.obtain_cookies = AsyncMock()
        mock_deser.return_value = session

        await session_manager._restore_or_create()

    session.refresh_access_token.assert_called_once()
    session.obtain_cookies.assert_called_once()


@pytest.mark.asyncio
async def test_restore_or_create_json_decode_error(session_manager):
    session_manager.redis.get = AsyncMock(return_value="not valid json{{{")
    session_manager.redis.delete = AsyncMock()
    with patch.object(
        session_manager, "_create_new_session", new_callable=AsyncMock
    ) as mock:
        await session_manager._restore_or_create()
    # JSONDecodeError перехватывается, создаётся новая сессия
    mock.assert_called_once()


@pytest.mark.asyncio
async def test_load_guard_account_success(session_manager, tmp_path, monkeypatch):
    guard_file = tmp_path / "test.maFile"
    guard_file.write_text(
        json.dumps(
            {
                "shared_secret": "dGVzdA==",
                "identity_secret": "dGVzdA==",
                "account_name": "user",
            }
        )
    )
    monkeypatch.setattr(settings, "STEAM_GUARD_FILE", str(guard_file))

    with patch(
        "app.services.steam.session_manager.SteamGuardAccount.from_mafile"
    ) as mock_from:
        mock_from.return_value = MagicMock()
        result = session_manager._load_guard_account()

    assert result is not None


@pytest.mark.asyncio
async def test_create_new_session_guard_confirmation(session_manager):
    session_manager.redis = None
    with (
        patch("app.services.steam.session_manager.SteamSession") as MockSession,
        patch(
            "app.services.steam.session_manager.retry_async", new=lambda f, *a, **k: f()
        ),
    ):
        session = MockSession.return_value
        session.with_credentials = AsyncMock(
            side_effect=GuardConfirmationRequired(
                confirmations=[], allowed_guard_types=["device"]
            )
        )
        session.submit_auth_code = AsyncMock()
        session.finalize = AsyncMock()
        session.obtain_cookies = AsyncMock()

        guard_account = MagicMock()
        guard_account.shared_secret.generate_auth_code.return_value = "ABCDE"
        with patch.object(
            session_manager, "_load_guard_account", return_value=guard_account
        ):
            await session_manager._create_new_session()

        session.submit_auth_code.assert_called_once_with("ABCDE", "device")


@pytest.mark.asyncio
async def test_create_new_session_guard_missing(session_manager):
    """Если Guard требуется, но .maFile нет — RuntimeError."""
    session_manager.redis = None
    with (
        patch("app.services.steam.session_manager.SteamSession") as MockSession,
        patch(
            "app.services.steam.session_manager.retry_async", new=lambda f, *a, **k: f()
        ),
    ):
        session = MockSession.return_value
        session.with_credentials = AsyncMock(
            side_effect=GuardConfirmationRequired(
                confirmations=[], allowed_guard_types=["device"]
            )
        )
        with patch.object(
            session_manager, "_load_guard_account", return_value=None
        ) and pytest.raises(RuntimeError, match="Steam Guard required"):
            await session_manager._create_new_session()


@pytest.mark.asyncio
async def test_create_new_session_saved_to_redis(session_manager):
    session_manager.redis = AsyncMock()
    session_manager.redis.setex = AsyncMock()
    with (
        patch("app.services.steam.session_manager.SteamSession") as MockSession,
        patch(
            "app.services.steam.session_manager.retry_async", new=lambda f, *a, **k: f()
        ),
    ):
        session = MockSession.return_value
        session.with_credentials = AsyncMock()
        session.finalize = AsyncMock()
        session.obtain_cookies = AsyncMock()
        session.serialize.return_value = {"data": "tokens"}

        await session_manager._create_new_session()

    session_manager.redis.setex.assert_called_once()


@pytest.mark.asyncio
async def test_close(session_manager):
    session_manager._session = MagicMock()
    session_manager._session.transport.close = AsyncMock()
    await session_manager.close()
    assert session_manager._session is None
