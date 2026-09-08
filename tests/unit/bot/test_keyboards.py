from app.bot.keyboards import (
    inventory_pagination, item_actions, subscription_choice,
    portfolio_pagination, tracked_item_actions, alert_period_keyboard,
    price_period_keyboard
)
from app.db.models import Item

def test_inventory_pagination_buttons():
    items = [("Item A", 1), ("Item B", 2), ("Item C", 3)]
    kb = inventory_pagination(items, page=0, items_per_page=2)
    # Проверяем, что клавиатура содержит кнопки предметов и пагинацию
    assert len(kb.inline_keyboard) == 3  # 2 предмета + 1 ряд навигации

def test_item_actions():
    kb = item_actions(item_id=1)
    assert len(kb.inline_keyboard) == 2
    assert kb.inline_keyboard[0][0].callback_data == "stats:1"

def test_price_period_keyboard():
    kb = price_period_keyboard(item_id=1)
    assert len(kb.inline_keyboard) == 1
    assert len(kb.inline_keyboard[0]) == 4

def test_portfolio_pagination_buttons():
    items = [Item(id=1, market_hash_name="Item A"), Item(id=2, market_hash_name="Item B")]
    kb = portfolio_pagination(items, page=0, items_per_page=2)
    assert len(kb.inline_keyboard) == 2  # 2 предмета + пагинация

def test_tracked_item_actions():
    kb = tracked_item_actions(item_id=5)
    # Проверяем, что есть 2 ряда и нужные callback_data
    assert kb.inline_keyboard[0][0].callback_data == "stats:5"
    assert kb.inline_keyboard[1][1].callback_data == "tracked_untrack:5"

def test_subscription_choice():
    kb = subscription_choice(item_id=3)
    assert kb.inline_keyboard[0][0].callback_data == "sub_add:3:daily"

def test_alert_period_keyboard():
    kb = alert_period_keyboard()
    assert kb.inline_keyboard[0][0].callback_data == "alert_period:24h"

def test_price_period_keyboard():
    kb = price_period_keyboard(item_id=7)
    assert len(kb.inline_keyboard[0]) == 4