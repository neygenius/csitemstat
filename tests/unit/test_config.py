import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_required_fields(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_defaults():
    settings = Settings(
        BOT_TOKEN="t",
        WEBHOOK_SECRET="s",
        WEBHOOK_URL="u",
        DB_USER="u",
        DB_PASSWORD="p",
        DB_HOST="h",
        DB_NAME="n",
        REDIS_URL="r",
        FERNET_KEY="k",
        STEAM_USERNAME="su",
        STEAM_PASSWORD="sp",
        STEAM_GUARD_FILE="sg",
    )
    assert settings.STEAM_AUTH_MODE == "aiosteampy"
    assert settings.STEAM_SESSION_TTL == 604800
    assert settings.STEAM_COOKIES == ""
    assert settings.APP_ID == 730
    assert settings.CURRENCY_SYMBOL == "₽"
