import pytest
from cryptography.fernet import Fernet

from app.config import settings

pytestmark = pytest.mark.integration


def test_fernet_key_is_valid():
    """Ключ должен быть валидным Fernet-ключом — иначе шифрование упадёт."""
    key = (
        settings.FERNET_KEY.encode()
        if isinstance(settings.FERNET_KEY, str)
        else settings.FERNET_KEY
    )
    # Fernet() сам бросит исключение при неверном ключе
    cipher = Fernet(key)
    # И ключ должен работать в обе стороны
    token = cipher.encrypt(b"ping")
    assert cipher.decrypt(token) == b"ping"


def test_database_url_is_async():
    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")


def test_sync_database_url_uses_psycopg2():
    assert settings.SYNC_DATABASE_URL.startswith("postgresql+psycopg2://")


def test_required_settings_present():
    required = (
        "BOT_TOKEN",
        "WEBHOOK_SECRET",
        "WEBHOOK_URL",
        "REDIS_URL",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_NAME",
        "FERNET_KEY",
        "STEAM_USERNAME",
        "STEAM_PASSWORD",
        "STEAM_GUARD_FILE",
    )
    for name in required:
        value = getattr(settings, name)
        assert value not in (None, ""), f"{name} must be set in the environment"
