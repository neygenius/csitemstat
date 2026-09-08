import io
from datetime import datetime

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import seaborn as sns

matplotlib.use("Agg")

from app.config import settings


def generate_price_chart(
    dates: list[datetime], prices: list[float], item_name: str
) -> bytes:
    """
    Создает PNG график цены и возвращает байты.
    """
    sns.set_style("whitegrid")
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)

    ax.plot(dates, prices, color="#2E86AB", linewidth=1.5)

    ax.set_title(item_name, fontsize=12, fontweight="bold", pad=10)
    ax.set_xlabel("Дата", fontsize=10)
    ax.set_ylabel(f"Цена ({settings.CURRENCY_SYMBOL})", fontsize=10)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate(rotation=30)

    sns.despine(left=True, bottom=True)

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
