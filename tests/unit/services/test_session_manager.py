from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosteampy.session import GuardConfirmationRequired

from app.config import settings
from app.services.steam.session_manager import SessionManager


@pytest.fixture
def session_manager():
    return SessionManager(redis_client=MagicMock())


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
            side_effect=Exception("refresh failed")
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
