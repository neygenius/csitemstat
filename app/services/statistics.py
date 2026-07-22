import numpy as np
from scipy import stats
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import ItemDailyStats

async def compute_trend(session: AsyncSession, item_id: int, window_days: int = 7):
    """Вычисляет наклон линейной регрессии и направление тренда."""
    since = date.today() - timedelta(days=window_days)
    stmt = select(ItemDailyStats.price).where(
        ItemDailyStats.item_id == item_id,
        ItemDailyStats.date >= since
    ).order_by(ItemDailyStats.date.asc())
    result = await session.execute(stmt)
    prices = [float(row[0]) for row in result.fetchall()]  # Decimal -> float
    if len(prices) < 2:
        return None, "stable"
    x = np.arange(len(prices))
    slope, _, _, _, _ = stats.linregress(x, prices)
    if slope > 0.01:
        direction = "up"
    elif slope < -0.01:
        direction = "down"
    else:
        direction = "stable"
    return slope, direction

def percent_change(current: float, old: float) -> float:
    if old == 0:
        return 0.0
    return ((current - old) / old) * 100