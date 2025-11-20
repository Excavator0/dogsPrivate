from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def make_type_keyboard(items: dict[str, str]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for item, code in items.items():
        builder.add(InlineKeyboardButton(text=str(item), callback_data=str(code)))
    builder.adjust(2)
    return builder


def make_sizes_keyboard(sizes: list[str]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for size in sizes:
        builder.add(InlineKeyboardButton(text=size, callback_data=f"size_{size.lower()}"))
    builder.adjust(3)
    return builder


def make_zone_keyboard(zones: list[tuple[str, str]]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for text, code in zones:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"zone_{code}"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_items"))
    builder.adjust(2)
    return builder


def make_customization_keyboard(show_ready_design: bool = False) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    # Показываем кнопку макетов только когда они доступны
    if show_ready_design:
        builder.add(InlineKeyboardButton(text="Готовый дизайн AIVADOG", callback_data="custom_ready"))
    builder.add(InlineKeyboardButton(text="Фото питомца без дизайна", callback_data="custom_photo"))
    builder.add(InlineKeyboardButton(text="Добавить стикеры", callback_data="custom_stickers"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_zones"))
    return builder


def make_main_menu_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔘 Выбрать изделие", callback_data="choose_item"))
    builder.add(InlineKeyboardButton(text="🔘 Посмотреть примеры дизайнов", callback_data="show_examples"))
    builder.add(InlineKeyboardButton(text="🔘 Инфо о бренде", callback_data="brand_info"))
    builder.adjust(1)
    return builder


def make_back_to_main_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Назад к выбору", callback_data="back_to_main"))
    return builder


def make_yes_no_keyboard(yes_data: str, no_data: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Да", callback_data=yes_data))
    builder.add(InlineKeyboardButton(text="Нет", callback_data=no_data))
    builder.adjust(2)
    return builder


def make_sticker_keyboard(stickers: list[tuple[str, str]]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for text, code in stickers:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"sticker_{code}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="Готово", callback_data="stickers_done"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="stickers_back"))
    return builder


def make_sticker_zone_keyboard(zones: list[tuple[str, str]]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for text, code in zones:
        builder.add(InlineKeyboardButton(text=text, callback_data=f"sticker_zone_{code}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="stickers_cancel"))
    return builder


def make_sticker_categories_keyboard(categories: list[tuple[str, str]]) -> InlineKeyboardBuilder:
    """
    Клавиатура выбора категории стикеров.
    categories: [(title, code), ...]
    """
    builder = InlineKeyboardBuilder()
    for title, code in categories:
        builder.add(InlineKeyboardButton(text=title, callback_data=f"sticker_cat_{code}"))
    if categories:
        builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="stickers_back"))
    return builder


def make_sticker_view_keyboard(current_index: int, total: int) -> InlineKeyboardBuilder:
    """
    Клавиатура для просмотра одного стикера:
    ⬅️ / ➡️ / Готово / Назад.
    """
    builder = InlineKeyboardBuilder()
    # Навигация влево/вправо
    if total > 1:
        builder.add(InlineKeyboardButton(text="⬅️", callback_data="sticker_prev"))
        builder.add(InlineKeyboardButton(text="➡️", callback_data="sticker_next"))
        builder.adjust(2)
    # Готово = добавить текущий и завершить (обработаем в sticker_browse)
    builder.row(InlineKeyboardButton(text="Готово ✅", callback_data="sticker_add"))
    # Назад к выбору зоны/категории
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="stickers_back"))
    return builder