import json
import logging
from pathlib import Path

from aiosteampy.constants import Platform
from aiosteampy.exceptions import SteamError
from aiosteampy.guard.account import MaFile, SteamGuardAccount
from aiosteampy.session import GuardConfirmationRequired, SteamSession
from aiosteampy.transport.exceptions import NetworkError, TransportError

from app.config import settings
from app.utils.retry import retry_async

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Управление жизненным циклом Steam сессии.
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._session: SteamSession | None = None

    async def get_session(self) -> SteamSession:
        """
        Возвращает активную сессию, при необходимости восстанавливая её.
        """
        if self._session is None:
            await self._restore_or_create()
        return self._session

    async def _restore_or_create(self) -> None:
        """
        Восстанавливает сессию из Redis или создаёт новую.
        """
        if self.redis:
            saved = await self.redis.get("steam:session:tokens")
            if saved:
                try:
                    session_data = json.loads(saved)
                    self._session = SteamSession.deserialize(session_data)

                    if self._session.cookies_are_valid:
                        logger.info("Steam session restored from Redis")
                        return
                    else:
                        # Пытаемся обновить токены и получить новые куки
                        try:
                            await self._session.refresh_access_token()
                            await self._session.obtain_cookies()
                            logger.info("Steam session restored and refreshed")
                            return
                        except (SteamError, TransportError) as e:
                            logger.warning(f"Failed to refresh restored session: {e}")
                            await self.redis.delete("steam:session:tokens")
                            self._session = None
                except (SteamError, TransportError) as e:
                    logger.warning(f"Failed to restore session from Redis: {e}")
                    self._session = None

        await self._create_new_session()

    def _load_guard_account(self) -> SteamGuardAccount | None:
        guard_path = Path(settings.STEAM_GUARD_FILE)
        if not guard_path.exists():
            logger.exception(f"Steam Guard file not found: {guard_path}")
            return None

        try:
            with open(guard_path, "r", encoding="utf-8") as f:
                mafile_data: MaFile = json.load(f)
            return SteamGuardAccount.from_mafile(mafile_data)
        except Exception:
            logger.exception("Failed to load Steam Guard account")
            return None

    async def _create_new_session(self) -> None:
        async def _login_flow():
            self._session = SteamSession(platform=Platform.WEB)
            try:
                await self._session.with_credentials(
                    settings.STEAM_USERNAME, settings.STEAM_PASSWORD
                )
            except GuardConfirmationRequired:
                guard_account = self._load_guard_account()
                if guard_account is None:
                    raise RuntimeError("Steam Guard required but .maFile not available")
                code = guard_account.shared_secret.generate_auth_code()
                await self._session.submit_auth_code(code, "device")

            await self._session.finalize()

            await retry_async(
                self._session.obtain_cookies,
                retries=5,
                delay=3.0,
                exceptions=(TimeoutError, ConnectionError, NetworkError),
            )

        await retry_async(
            _login_flow,
            retries=5,
            delay=3.0,
            exceptions=(TimeoutError, ConnectionError, NetworkError),
        )

        logger.info(f"Steam session created for {settings.STEAM_USERNAME}")

        if self.redis:
            session_dump = self._session.serialize()
            await self.redis.setex(
                "steam:session:tokens",
                settings.STEAM_SESSION_TTL,
                json.dumps(session_dump),
            )

    async def close(self) -> None:
        if self._session:
            await self._session.transport.close()
            self._session = None
