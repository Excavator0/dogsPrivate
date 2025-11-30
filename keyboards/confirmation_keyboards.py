from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def confirm_or_setting_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Продолжить", callback_data="confirm"))
    builder.add(InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"))
    return builder


def checkout_or_edit_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Подтвердить стоимость", callback_data="checkout"))
    builder.add(InlineKeyboardButton(text="Вернуться", callback_data="back_to_preview"))
    return builder


def edit_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Сменить изделие", callback_data="ask_item"))
    builder.add(InlineKeyboardButton(text="Изменить размер изделия", callback_data="ask_order_size"))
    builder.add(InlineKeyboardButton(text="Настройки макета", callback_data="edit_settings"))
    builder.add(InlineKeyboardButton(text="Начать заново", callback_data="start_again"))
    builder.add(InlineKeyboardButton(text="Назад", callback_data="edit_back"))
    builder.adjust(2, 2)
    return builder


def final_preview_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Да, всё супер", callback_data="preview_ok"))
    builder.add(InlineKeyboardButton(text="Связаться с дизайнером ✍️", callback_data="preview_designer"))
    builder.add(InlineKeyboardButton(text="Хочу ещё выбрать принт", callback_data="preview_more"))
    builder.add(InlineKeyboardButton(text="Поделиться и получить скидку", callback_data="preview_share"))
    builder.adjust(1)
    return builder
