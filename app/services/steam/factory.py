from app.config import settings
from app.services.steam.interface import ISteamProvider
from app.services.steam.provider import SteamProvider
from app.services.steam.session_manager import SessionManager

def create_steam_provider(redis_client=None) -> ISteamProvider:
    """Создаёт провайдер Steam API в зависимости от конфигурации."""
    mode = settings.STEAM_AUTH_MODE

    if mode == "aiosteampy":
        session_manager = SessionManager(redis_client)
        return SteamProvider(session_manager)
    else:
        # Fallback на cookies (если потребуется)
        return 