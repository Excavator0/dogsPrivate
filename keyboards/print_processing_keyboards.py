from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def make_settings_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Изменить размер",
        callback_data="change_size"
    ))
    builder.add(InlineKeyboardButton(
        text="Сдвинуть принт",
        callback_data="move_print"
    ))
    builder.add(InlineKeyboardButton(
        text="Повернуть принт",
        callback_data="rotate_print"
    ))
    builder.add(InlineKeyboardButton(
        text="Сменить сторону / зону",
        callback_data="change_side"
    ))
    builder.add(InlineKeyboardButton(
        text="Удалить фон",
        callback_data="delete_bg"
    ))
    builder.add(InlineKeyboardButton(
        text="Удалить принт",
        callback_data="delete_print"
    ))
    builder.add(InlineKeyboardButton(
        text="Отменить изменения",
        callback_data="reset_edit"
    ))
    builder.add(InlineKeyboardButton(
        text="Стикеры",
        callback_data="edit_stickers"
    ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="settings_back"
    ))
    builder.adjust(2, 2, 2, 1, 1, 1)
    return builder


def make_remove_bg_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Отменить удаление",
        callback_data="restore_bg"
    ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="settings"
    ))
    return builder


def make_print_size_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Увеличить",
        callback_data="increase_size"
    ))
    builder.add(InlineKeyboardButton(
        text="Уменьшить",
        callback_data="decrease_size"
    ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="settings"
    ))
    return builder


def make_move_print_keyboard():
    builder = InlineKeyboardBuilder()

    builder.add(InlineKeyboardButton(
        text="Центрировать",
        callback_data="move_centre"
    ))
    builder.add(InlineKeyboardButton(
        text="Вверх",
        callback_data="move_up"
    ))
    builder.add(InlineKeyboardButton(
        text="Влево",
        callback_data="move_left"
    ))
    builder.add(InlineKeyboardButton(
        text="Вправо",
        callback_data="move_right"
    ))
    builder.add(InlineKeyboardButton(
        text="Вниз",
        callback_data="move_down"
    ))

    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="settings"
    ))
    builder.adjust(1, 1, 2, 1, 1)

    return builder


def make_rotate_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Влево",
        callback_data="rotate_left"
    ))
    builder.add(InlineKeyboardButton(
        text="Вправо",
        callback_data="rotate_right"
    ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="settings"
    ))

    return builder


def make_side_keyboard(side):
    builder = InlineKeyboardBuilder()
    if side == 0:
        builder.add(InlineKeyboardButton(
            text="Задняя сторона",
            callback_data="side_back"
        ))
    else:
        builder.add(InlineKeyboardButton(
            text="Передняя сторона",
            callback_data="side_front"
        ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="settings"
    ))

    return builder


def make_stickers_manage_keyboard(active_index, total, back_callback: str = "settings"):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Добавить стикер/надпись",
        callback_data="st_add_new"
    ))
    builder.add(InlineKeyboardButton(
        text="Выбрать стикер",
        callback_data="st_select"
    ))
    builder.add(InlineKeyboardButton(
        text="Двигать",
        callback_data="st_move"
    ))
    builder.add(InlineKeyboardButton(
        text="Размер",
        callback_data="st_size"
    ))
    builder.add(InlineKeyboardButton(
        text="Повернуть",
        callback_data="st_rotate"
    ))
    builder.add(InlineKeyboardButton(
        text="Удалить",
        callback_data="st_delete"
    ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data=back_callback
    ))
    builder.adjust(1, 2, 2, 1, 1)
    return builder


def make_stickers_select_keyboard(total: int):
    builder = InlineKeyboardBuilder()
    for i in range(total):
        builder.add(InlineKeyboardButton(
            text=f"Стикер {i + 1}",
            callback_data=f"st_pick_{i}"
        ))
    if total:
        builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="st_manage"))
    return builder


def make_sticker_move_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Центрировать", callback_data="st_move_centre"))
    builder.add(InlineKeyboardButton(text="Вверх", callback_data="st_move_up"))
    builder.add(InlineKeyboardButton(text="Влево", callback_data="st_move_left"))
    builder.add(InlineKeyboardButton(text="Вправо", callback_data="st_move_right"))
    builder.add(InlineKeyboardButton(text="Вниз", callback_data="st_move_down"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st_manage"))
    builder.adjust(1, 1, 2, 1, 1)
    return builder


def make_sticker_size_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Увеличить", callback_data="st_increase_size"))
    builder.add(InlineKeyboardButton(text="Уменьшить", callback_data="st_decrease_size"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st_manage"))
    return builder


def make_sticker_rotate_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Влево", callback_data="st_rotate_left"))
    builder.add(InlineKeyboardButton(text="Вправо", callback_data="st_rotate_right"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st_manage"))
    return builder