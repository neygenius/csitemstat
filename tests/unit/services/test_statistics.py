import pytest
from unittest.mock import AsyncMock
from datetime import date, timedelta
from app.services.statistics import compute_trend, percent_change
from app.db.models import ItemDailyStats

@pytest.mark.asyncio
async def test_compute_trend_up(mock_session):
    prices = [10, 11, 12, 13, 14, 15, 16]
    mock_session.execute.return_value.fetchall.return_value = [(p,) for p in prices]
    
    slope, direction = await compute_trend(mock_session, item_id=1, window_days=7)
    
    assert slope > 0
    assert direction == "up"

@pytest.mark.asyncio
async def test_compute_trend_down(mock_session):
    prices = [16, 15, 14, 13, 12, 11, 10]
    mock_session.execute.return_value.fetchall.return_value = [(p,) for p in prices]
    
    slope, direction = await compute_trend(mock_session, item_id=1, window_days=7)
    
    assert slope < 0
    assert direction == "down"

@pytest.mark.asyncio
async def test_compute_trend_stable(mock_session):
    prices = [10, 10, 10, 10, 10, 10, 10]
    mock_session.execute.return_value.fetchall.return_value = [(p,) for p in prices]
    
    slope, direction = await compute_trend(mock_session, item_id=1, window_days=7)
    
    assert direction == "stable"

@pytest.mark.asyncio
async def test_compute_trend_insufficient_data(mock_session):
    mock_session.execute.return_value.fetchall.return_value = [(10,)]
    
    slope, direction = await compute_trend(mock_session, item_id=1, window_days=7)
    
    assert slope is None
    assert direction == "stable"

@pytest.mark.parametrize("current, old, expected", [
    (110, 100, 10.0),
    (90, 100, -10.0),
    (0, 100, -100.0),
    (100, 0, 0.0),
])
def test_percent_change(current, old, expected):
    assert percent_change(current, old) == expected