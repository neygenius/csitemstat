import pytest
from unittest.mock import AsyncMock
from app.services.inventory import fetch_grouped_inventory, group_inventory

@pytest.mark.asyncio
async def test_fetch_grouped_inventory_success(mock_steam_client):
    # Arrange
    mock_steam_client.get_inventory = AsyncMock(return_value={
        "success": True,
        "rgInventory": {
            "1": {"classid": "111", "instanceid": "222"},
            "2": {"classid": "111", "instanceid": "222"},
            "3": {"classid": "333", "instanceid": "444"}
        },
        "rgDescriptions": {
            "111_222": {"market_hash_name": "Item A"},
            "333_444": {"market_hash_name": "Item B"}
        }
    })
    
    # Act
    result = await fetch_grouped_inventory(mock_steam_client, 123456, 730)
    
    # Assert
    assert result == {"Item A": 2, "Item B": 1}

@pytest.mark.asyncio
async def test_fetch_grouped_inventory_failure(mock_steam_client):
    mock_steam_client.get_inventory = AsyncMock(return_value={"success": False})
    result = await fetch_grouped_inventory(mock_steam_client, 123456, 730)
    assert result == {}

def test_group_inventory():
    raw = {"AK-47": 5, "M4A4": 1, "AWP": 3}
    grouped = group_inventory(raw)
    assert grouped == [("AK-47", 5), ("AWP", 3), ("M4A4", 1)]