import asyncio
import pytest

@pytest.fixture(scope="session")
def event_loop():
    """Создаёт общий event loop для всех тестов."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()