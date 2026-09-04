from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ISteamProvider(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        """Первичная инициализация и аутентификация."""
        pass

    @abstractmethod
    async def ensure_authenticated(self) -> bool:
        """Проверка и восстановление сессии при необходимости."""
        pass

    @abstractmethod
    async def get_price_overview(self, app_id: int, market_hash_name: str) -> Dict[str, Any]:
        """Получение текущей цены предмета."""
        pass

    @abstractmethod
    async def get_price_history(self, app_id: int, market_hash_name: str) -> List[List]:
        """Получение истории цен в формате [[date_str, price, volume_str], ...]."""
        pass

    @abstractmethod
    async def get_inventory(self, steam_id64: int, app_id: int) -> Dict[str, Any]:
        """Получение инвентаря пользователя."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Освобождение ресурсов."""
        pass