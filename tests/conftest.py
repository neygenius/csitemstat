import asyncio
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = Path(item.fspath)
        if "unit" in path.parts:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session")
def event_loop():
    """Создаёт общий event loop для всех тестов."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
