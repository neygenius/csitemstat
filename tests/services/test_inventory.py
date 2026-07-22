import pytest
from app.services.inventory import fetch_grouped_inventory, group_inventory

@pytest.mark.asyncio
async def test_fetch_grouped_inventory(steam_client_mock):
    # Мок-ответ инвентаря
    steam_client_mock.get_inventory.return_value = {
        "success": True,
        "rgInventory": {
            "1": {"classid": "111", "instanceid": "222"},
            "2": {"classid": "111", "instanceid": "222"},  # дубликат -> count 2
            "3": {"classid": "333", "instanceid": "444"}
        },
        "rgDescriptions": {
            "111_222": {"market_hash_name": "Item A"},
            "333_444": {"market_hash_name": "Item B"}
        }
    }
    result = await fetch_grouped_inventory(steam_client_mock, 123456, 730)
    assert result == {"Item A": 2, "Item B": 1}

def test_group_inventory():
    raw = {"AK-47": 5, "M4A4": 1, "AWP": 3}
    grouped = group_inventory(raw)
    assert grouped == [("AK-47", 5), ("AWP", 3), ("M4A4", 1)]  # сортировка по имени