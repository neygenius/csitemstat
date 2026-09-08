from datetime import datetime, timedelta, timezone

from app.services.plotter import generate_price_chart


def test_generate_price_chart_returns_png():
    dates = [
        datetime.now(tz=timezone.utc).date() - timedelta(days=i)
        for i in range(6, -1, -1)
    ]
    prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    img_bytes = generate_price_chart(dates, prices, "Test Item")
    assert isinstance(img_bytes, bytes)
    assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(img_bytes) > 500


def test_generate_price_chart_single_point():
    img_bytes = generate_price_chart(
        [datetime.now(tz=timezone.utc).date()], [10.0], "Single"
    )
    assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"
