from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

colors = {"Чёрный": "black", "Белый": "white", "Красный": "red", "Жёлтый": "yellow",
          "Синий": "blue", "Фиолетовый": "magenta"}


def make_type_keyboard(items):
    builder = InlineKeyboardBuilder()
    for item, code in items.items():
        builder.add(InlineKeyboardButton(
            text=str(item),
            callback_data=str(code)
        ))
    builder.adjust(3, 2)

    return builder


def make_sizes_keyboard(sizes):
    builder = InlineKeyboardBuilder()
    for size in sizes:
        builder.add(InlineKeyboardButton(
            text=str(size),
            callback_data=str(size).lower()
        ))
    return builder


def make_colors_keyboard():
    builder = InlineKeyboardBuilder()
    for color, code in colors.items():
        builder.add(InlineKeyboardButton(
            text=str(color),
            callback_data=code
        ))
    builder.adjust(3, 3)
    return builder


def make_color_confirm_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Далее",
        callback_data="getting_print"
    ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="change_color"
    ))

    return builder