from abc import ABC, abstractmethod
from typing import Any


class ISteamProvider(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        """Первичная инициализация и аутентификация."""

    @abstractmethod
    async def ensure_authenticated(self) -> bool:
        """Проверка и восстановление сессии при необходимости."""

    @abstractmethod
    async def get_price_overview(
        self, app_id: int, market_hash_name: str
    ) -> dict[str, Any]:
        """Получение текущей цены предмета."""

    @abstractmethod
    async def get_price_history(self, app_id: int, market_hash_name: str) -> list[list]:
        """Получение истории цен в формате [[date_str, price, volume_str], ...]."""

    @abstractmethod
    async def get_inventory(self, steam_id64: int, app_id: int) -> dict[str, Any]:
        """Получение инвентаря пользователя."""

    @abstractmethod
    async def close(self) -> None:
        """Освобождение ресурсов."""
