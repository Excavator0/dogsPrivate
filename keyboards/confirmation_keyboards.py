from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def confirm_or_setting_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Подтвердить",
        callback_data="confirm"
    ))
    builder.add(InlineKeyboardButton(
        text="Настройки",
        callback_data="settings"
    ))
    return builder


def checkout_or_edit_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Перейти к оплате",
        callback_data="checkout"
    ))
    builder.add(InlineKeyboardButton(
        text="Изменить заказ",
        callback_data="edit"
    ))
    return builder


def edit_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Сменить изделие",
        callback_data="ask_item"
    ))
    builder.add(InlineKeyboardButton(
        text="Изменить размер изделия",
        callback_data="ask_order_size"
    ))
    builder.add(InlineKeyboardButton(
        text="Изменить цвет изделия",
        callback_data="ask_color"
    ))
    builder.add(InlineKeyboardButton(
        text="Настройки макета",
        callback_data="edit_settings"
    ))
    builder.add(InlineKeyboardButton(
        text="Начать заново",
        callback_data="start_again"
    ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="edit_back"
    ))
    builder.adjust(2, 2, 2)

    return builder
