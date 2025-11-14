from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def make_row_keyboard(items: list[str]) -> ReplyKeyboardMarkup:
    rows = []
    if len(items) == 5:
        rows.append([KeyboardButton(text=item) for item in items[:3]])
        rows.append([KeyboardButton(text=item) for item in items[3:5]])
    elif len(items) == 6:
        rows.append([KeyboardButton(text=item) for item in items[:3]])
        rows.append([KeyboardButton(text=item) for item in items[3:6]])
    else:
        rows.append([KeyboardButton(text=item) for item in items])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)