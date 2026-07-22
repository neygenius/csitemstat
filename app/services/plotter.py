import io
import matplotlib
from app.config import settings
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Tuple

def generate_price_chart(dates: List[datetime], prices: List[float], item_name: str) -> bytes:
    """Создает PNG график цены и возвращает байты."""
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(dates, prices, marker='.', linestyle='-', color='#1f77b4')
    ax.set_title(f"Price history: {item_name}")
    ax.set_xlabel("Date")
    ax.set_ylabel(f"Price ({settings.CURRENCY_SYMBOL})")
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()
    ax.grid(True, linestyle='--', alpha=0.7)
    
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()