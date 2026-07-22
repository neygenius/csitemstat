from app.services.plotter import generate_price_chart
from datetime import datetime, timedelta

def test_generate_price_chart():
    dates = [datetime.today() - timedelta(days=i) for i in range(6, -1, -1)]
    prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    img_bytes = generate_price_chart(dates, prices, "Test Item")
    assert isinstance(img_bytes, bytes)
    assert len(img_bytes) > 500
    # Проверим, что это PNG
    assert img_bytes[:8] == b'\x89PNG\r\n\x1a\n'