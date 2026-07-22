import pytest
from app.config import Settings, settings

def test_database_url_property():
    s = Settings(
        BOT_TOKEN="t",
        WEBHOOK_SECRET="s",
        WEBHOOK_URL="http://u",
        DB_USER="user",
        DB_PASSWORD="pass",
        DB_HOST="host",
        DB_NAME="name",
        REDIS_URL="r",
        FERNET_KEY="k"
    )
    assert "postgresql+asyncpg://user:pass@host:5432/name" == s.DATABASE_URL
    assert "postgresql+psycopg2://user:pass@host:5432/name" == s.SYNC_DATABASE_URL