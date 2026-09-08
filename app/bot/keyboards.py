from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Item


def inventory_pagination(
    items: list[tuple[str, int]], page: int, items_per_page: int = 10
) -> InlineKeyboardMarkup:
    """
    Кнопки пагинации инвентаря.
    """
    builder = InlineKeyboardBuilder()
    start = page * items_per_page
    end = start + items_per_page
    for name, cnt in items[start:end]:
        builder.button(text=f"🔹 {name} ({cnt} шт.)", callback_data=f"add_track:{name}")
    builder.adjust(1)

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_page:{page - 1}")
        )
    if end < len(items):
        nav_buttons.append(
            InlineKeyboardButton(text="Вперед ▶️", callback_data=f"inv_page:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)
    return builder.as_markup()


def item_actions(item_id: int) -> InlineKeyboardMarkup:
    """
    Кнопки действий с предметом.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика", callback_data=f"stats:{item_id}"
                ),
                InlineKeyboardButton(
                    text="🔔 Подписка", callback_data=f"subs:{item_id}"
                ),
            ],
            [InlineKeyboardButton(text="⏰ Алерт", callback_data=f"alert:{item_id}")],
        ]
    )


def subscription_choice(item_id: int) -> InlineKeyboardMarkup:
    """
    Кнопки выбора периода для subs.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 Ежедневно", callback_data=f"sub_add:{item_id}:daily"
                ),
                InlineKeyboardButton(
                    text="📆 Еженедельно", callback_data=f"sub_add:{item_id}:weekly"
                ),
            ]
        ]
    )


def portfolio_pagination(
    items: list[Item], page: int, items_per_page: int = 10
) -> InlineKeyboardMarkup:
    """
    Кнопки пагинации портфеля.
    """
    builder = InlineKeyboardBuilder()
    start = page * items_per_page
    end = start + items_per_page
    for item in items[start:end]:
        builder.button(
            text=f"🔸 {item.market_hash_name}", callback_data=f"tracked_item:{item.id}"
        )
    builder.adjust(1)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Назад", callback_data=f"portfolio_page:{page - 1}"
            )
        )
    if end < len(items):
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперед ▶️", callback_data=f"portfolio_page:{page + 1}"
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)
    return builder.as_markup()


def tracked_item_actions(item_id: int) -> InlineKeyboardMarkup:
    """
    Кнопки действий с отслеживаемым предметом.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика", callback_data=f"stats:{item_id}"
                ),
                InlineKeyboardButton(
                    text="🔔 Подписки", callback_data=f"tracked_subs:{item_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏰ Алерты", callback_data=f"tracked_alerts:{item_id}"
                ),
                InlineKeyboardButton(
                    text="⚠️ Удалить из портфеля",
                    callback_data=f"tracked_untrack:{item_id}",
                ),
            ],
        ]
    )


def alert_period_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопки выбора периода для alert.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="24 часа", callback_data="alert_period:24h"),
                InlineKeyboardButton(text="7 дней", callback_data="alert_period:7d"),
            ]
        ]
    )


def price_period_keyboard(item_id: int) -> InlineKeyboardMarkup:
    """
    Кнопки выбора временного окна графика.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="7 дней", callback_data=f"price_period:{item_id}:7"
                ),
                InlineKeyboardButton(
                    text="30 дней", callback_data=f"price_period:{item_id}:30"
                ),
                InlineKeyboardButton(
                    text="90 дней", callback_data=f"price_period:{item_id}:90"
                ),
                InlineKeyboardButton(
                    text="Всё время", callback_data=f"price_period:{item_id}:all"
                ),
            ]
        ]
    )
