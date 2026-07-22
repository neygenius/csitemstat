from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def inventory_pagination(items: list[tuple[int, str, int]], page: int, items_per_page: int = 10) -> InlineKeyboardMarkup:
    """
    Клавиатура пагинации инвентаря: item_id, market_hash_name, count
    """
    builder = InlineKeyboardBuilder()
    start = page * items_per_page
    end = start + items_per_page
    for item_id, name, cnt in items[start:end]:
        builder.button(text=f"🔹 {name} ({cnt} шт.)", callback_data=f"add_track:{item_id}")
    builder.adjust(1)

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_page:{page-1}"))
    if end < len(items):
        nav_buttons.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"inv_page:{page+1}"))
    if nav_buttons:
        builder.row(*nav_buttons)
    return builder.as_markup()

def item_actions(item_id: int) -> InlineKeyboardMarkup:
    """
    Кнопки действий с предметом
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data=f"stats:{item_id}"),
         InlineKeyboardButton(text="🔔 Подписки", callback_data=f"subs:{item_id}")],
        [InlineKeyboardButton(text="⏰ Алерт", callback_data=f"alert:{item_id}")]
    ])

def subscription_choice(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Ежедневно", callback_data=f"sub_add:{item_id}:daily"),
         InlineKeyboardButton(text="📆 Еженедельно", callback_data=f"sub_add:{item_id}:weekly")]
    ])