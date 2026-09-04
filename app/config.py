import os
from sqlalchemy.engine import URL
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_TOKEN: str
    WEBHOOK_SECRET: str
    WEBHOOK_URL : str
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_NAME: str
    REDIS_URL : str
    STEAM_USERNAME: str
    STEAM_PASSWORD: str
    STEAM_GUARD_FILE: str
    STEAM_AUTH_MODE: str = "aiosteampy"         # "aiosteampy" | "cookies"
    STEAM_SESSION_TTL: int = 604800
    STEAM_COOKIES: str = ""                     # обратная совместимость
    FERNET_KEY: str
    APP_ID: int = 730
    CURRENCY_SYMBOL: str = "₽"

    @property
    def DATABASE_URL(self) -> str:
        """
        Async URL (for application).
        """
        return URL.create(
            "postgresql+asyncpg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=5432,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """
        Sync URL (for Alembic).
        """
        return URL.create(
            "postgresql+psycopg2",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=5432,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)

    class Config:
        env_file = ".env"

settings = Settings()
