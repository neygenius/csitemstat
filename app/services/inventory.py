import logging
from typing import Dict, Tuple

from app.services.steam_client import SteamClient

logger = logging.getLogger(__name__)


async def fetch_grouped_inventory(steam_client: SteamClient, steam_id64: int, app_id: int) -> Dict[str, int]:
    """
    Получает инвентарь из Steam и возвращает словарь {market_hash_name: count}.
    """
    data = await steam_client.get_inventory(steam_id64, app_id)
    if not data.get("success"):
        logger.warning(f"Inventory not available for steam_id={steam_id64}")
        return {}
    
    rg_inventory = data.get("rgInventory", {})

    # Собираем classid-instanceid для быстрого доступа к описаниям
    items_count = {}
    for asset_id, asset in rg_inventory.items():
        classid = asset.get("classid")
        instanceid = asset.get("instanceid")
        key = f"{classid}_{instanceid}"

        # Ищем описание предмета в rgDescriptions
        description = data.get("rgDescriptions", {}).get(key)
        if description:
            market_hash_name = description.get("market_hash_name")
            if market_hash_name:
                items_count[market_hash_name] = items_count.get(market_hash_name, 0) + 1
        else:
            pass
    return items_count


def group_inventory(raw_inventory: dict) -> list:
    """
    Преобразует {name: count} в список кортежей (name, count).
    """
    return sorted(raw_inventory.items(), key=lambda x: x[0])