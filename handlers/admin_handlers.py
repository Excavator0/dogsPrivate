import asyncio
import json
from datetime import datetime
from functools import wraps
from typing import Iterable, List, Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_ID
from database.db import Database
from services.exporter import generate_users_excel

router = Router()
storage = Database()

ORDER_STATUS_CHOICES = [
    ("paid", "Оплачен"),
    ("work", "В работе"),
    ("approval", "На согласовании"),
    ("print", "В печати"),
    ("ready", "Готов"),
    ("shipped", "Отправлен"),
]

ORDER_STATUS_MESSAGES = {
    "В работе": "Дизайнеры уже готовят твой макет 🐾 Мы пришлём предпросмотр на согласование, как только он будет готов.",
    "На согласовании": "Твой финальный макет готов! 👀 Проверь, всё ли нравится и дай знать, если нужны правки.",
    "В печати": "Отлично 💛 Мы запускаем печать твоего изделия. Сообщим, как только можно будет забирать или организуем доставку.",
    "Готов": (
        "Твоя вещь готова! 🎉\n"
        "📍 Забери заказ в студии AIVADOG (Обводного канала, 223-225)\n"
        "или выбери доставку:"
    ),
    "Отправлен": "Заказ передан службе доставки. Мы сообщим трек-номер, как только получим подтверждение от курьера.",
}

MAILING_SEGMENTS = {
    "all": "Все пользователи",
    "active_90": "Активные за 90 дней",
    "ordered": "Сделавшие заказ",
    "new_30": "Новые за 30 дней",
}

DELIVERY_CALLBACKS = {
    "delivery_pickup": "Самовывоз",
    "delivery_courier": "Курьер по городу",
    "delivery_cdek": "Отправка СДЭКом",
}


class MailingStates(StatesGroup):
    choosing_segment = State()
    typing_text = State()
    waiting_photo = State()
    waiting_buttons = State()
    choosing_mode = State()
    waiting_schedule = State()
    waiting_test_recipients = State()


def admin_only(handler):
    @wraps(handler)
    async def wrapped(event, *args, **kwargs):
        user = event.from_user if hasattr(event, "from_user") else None
        if not user or user.id != ADMIN_ID:
            return
        return await handler(event, *args, **kwargs)

    return wrapped


def build_admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Последние заказы", callback_data="admin_last_orders"))
    builder.add(InlineKeyboardButton(text="Экспорт пользователей", callback_data="admin_export_users"))
    builder.add(InlineKeyboardButton(text="Создать рассылку", callback_data="admin_start_mailing"))
    builder.adjust(1)
    return builder.as_markup()


@router.message(Command("admin"))
@admin_only
async def admin_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Меню администратора AIVADOG:", reply_markup=build_admin_menu())


@router.callback_query(F.data == "admin_last_orders")
@admin_only
async def show_last_orders(callback: CallbackQuery):
    orders = storage.list_recent_orders(10)
    if not orders:
        await callback.message.answer("Пока нет заказов.")
        return
    for row in orders:
        text = (
            f"#{row['order_number']} — {row['item_code']} ({row['size']})\n"
            f"Статус: {row['status']}\n"
            f"Клиент: {row['full_name']} / {row['phone'] or '—'}"
        )
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="Подробнее", callback_data=f"admin_order_{row['id']}"))
        await callback.message.answer(text, reply_markup=builder.as_markup())


def _format_order_details(order) -> str:
    stickers = json.loads(order["stickers"]) if order["stickers"] else []
    notes = json.loads(order["notes_json"]) if order["notes_json"] else {}
    design_name = notes.get("ready_design_title")
    lines = [
        f"Заказ #{order['order_number']}",
        f"Изделие: {order['item_code']} • {order['size']}",
        f"Зона: {order['zone']}",
        f"Кастомизация: {order['customization']}",
        f"Стикеры: {', '.join(stickers) if stickers else 'Без стикеров'}",
        f"Имя питомца: {order['pet_name'] or '—'}",
    ]
    if design_name:
        lines.append(f"Выбранный макет: {design_name}")
    lines.extend(
        [
            f"Статус: {order['status']}",
            f"Стоимость: {order['total_price'] or order['base_price']} ₽",
            f"Контакты: {order['contact_phone'] or '—'} / {order['contact_email'] or '—'}",
            f"Клиент: {order['full_name']} (@{order['username'] or '—'})",
        ]
    )
    return "\n".join(lines)


@router.callback_query(F.data.startswith("admin_order_"))
@admin_only
async def show_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[-1])
    order = storage.get_order_with_user(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    history = storage.get_order_history(order_id)
    history_lines = [f"{row['created_at']}: {row['status']}" for row in history]
    text = _format_order_details(order)
    if history_lines:
        text += "\n\nИстория статусов:\n" + "\n".join(history_lines)
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Изменить статус", callback_data=f"admin_status_{order_id}"))
    builder.add(InlineKeyboardButton(text="Запросить контакты", callback_data=f"admin_request_contacts_{order_id}"))
    builder.adjust(1)
    await callback.message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("admin_request_contacts_"))
@admin_only
async def remind_contacts(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[-1])
    order = storage.get_order_with_user(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await callback.bot.send_message(
        order["tg_id"],
        "Нам нужны актуальные контакты для связи по заказу. Напиши, пожалуйста, имя и удобный номер телефона/почту.",
    )
    await callback.answer("Сообщение отправлено клиенту")


@router.callback_query(F.data.startswith("admin_status_"))
@admin_only
async def choose_status(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[-1])
    builder = InlineKeyboardBuilder()
    for slug, title in ORDER_STATUS_CHOICES:
        builder.add(InlineKeyboardButton(text=title, callback_data=f"admin_setstatus_{order_id}_{slug}"))
    builder.adjust(2)
    await callback.message.answer("Выбери новый статус заказа:", reply_markup=builder.as_markup())


async def _notify_status(bot, order, status: str):
    text = ORDER_STATUS_MESSAGES.get(status)
    if not text:
        return
    if status == "Готов":
        builder = InlineKeyboardBuilder()
        for cb_data, label in DELIVERY_CALLBACKS.items():
            builder.add(InlineKeyboardButton(text=label, callback_data=cb_data))
        builder.adjust(1)
        await bot.send_message(order["tg_id"], text, reply_markup=builder.as_markup())
        builder2 = InlineKeyboardBuilder()
        builder2.add(InlineKeyboardButton(text="Прислать фото изделия", callback_data=f"ugc_start_{order['id']}"))
        await bot.send_message(
            order["tg_id"],
            "Хочешь скидку на следующий заказ? Пришли фото готового изделия — нажми «Прислать фото» ниже 👇",
            reply_markup=builder2.as_markup(),
        )
    else:
        await bot.send_message(order["tg_id"], text)


@router.callback_query(F.data.startswith("admin_setstatus_"))
@admin_only
async def set_status(callback: CallbackQuery):
    _, _, order_id_str, slug = callback.data.split("_", 3)
    order_id = int(order_id_str)
    mapping = dict(ORDER_STATUS_CHOICES)
    status = mapping.get(slug)
    if not status:
        await callback.answer("Неизвестный статус", show_alert=True)
        return
    order = storage.get_order_with_user(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    storage.log_status(order_id, status, f"Изменено админом {callback.from_user.id}")
    await callback.answer(f"Статус обновлён: {status}")
    await _notify_status(callback.bot, order, status)


@router.callback_query(F.data == "admin_export_users")
@admin_only
async def export_users(callback: CallbackQuery):
    rows = storage.fetch_users_summary()
    path = generate_users_excel(rows)
    await callback.message.answer_document(document=path.open("rb"), caption="Выгрузка пользователей")


@router.callback_query(F.data == "admin_start_mailing")
@admin_only
async def start_mailing(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    for segment, title in MAILING_SEGMENTS.items():
        builder.add(InlineKeyboardButton(text=title, callback_data=f"mailing_segment_{segment}"))
    builder.adjust(1)
    await state.set_state(MailingStates.choosing_segment)
    await callback.message.answer("Выбери сегмент для рассылки:", reply_markup=builder.as_markup())


@router.callback_query(MailingStates.choosing_segment, F.data.startswith("mailing_segment_"))
@admin_only
async def mailing_segment_chosen(callback: CallbackQuery, state: FSMContext):
    segment = callback.data.replace("mailing_segment_", "")
    await state.update_data({"segment": segment})
    await state.set_state(MailingStates.typing_text)
    await callback.message.answer("Пришли текст рассылки (поддерживается HTML):")


@router.message(MailingStates.typing_text)
@admin_only
async def mailing_text(message: Message, state: FSMContext):
    await state.update_data({"text": message.html_text})
    await state.set_state(MailingStates.waiting_photo)
    await message.answer("Пришли изображение (JPEG/PNG до 5 МБ) или напиши «пропустить».")


@router.message(MailingStates.waiting_photo, F.photo)
@admin_only
async def mailing_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data({"photo_id": file_id})
    await state.set_state(MailingStates.waiting_buttons)
    await message.answer("Введи до 3 кнопок (формат: Текст|https://пример) по одной строке или напиши «нет».")


@router.message(MailingStates.waiting_photo, F.text.func(lambda value: value and value.lower() == "пропустить"))
@admin_only
async def mailing_skip_photo(message: Message, state: FSMContext):
    await state.update_data({"photo_id": None})
    await state.set_state(MailingStates.waiting_buttons)
    await message.answer("Введи до 3 кнопок (формат: Текст|https://пример) по одной строке или напиши «нет».")


@router.message(MailingStates.waiting_buttons)
@admin_only
async def mailing_buttons(message: Message, state: FSMContext):
    buttons_raw = []
    if message.text.lower().strip() != "нет":
        for line in message.text.splitlines():
            if "|" in line:
                title, url = line.split("|", 1)
                buttons_raw.append({"text": title.strip(), "url": url.strip()})
    await state.update_data({"buttons": buttons_raw[:3]})
    await state.set_state(MailingStates.choosing_mode)
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Тестовая", callback_data="mailing_mode_test"))
    builder.add(InlineKeyboardButton(text="Полная", callback_data="mailing_mode_full"))
    builder.adjust(2)
    await message.answer("Выбери тип рассылки:", reply_markup=builder.as_markup())


@router.callback_query(MailingStates.choosing_mode, F.data == "mailing_mode_test")
@admin_only
async def mailing_mode_test(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"mode": "test"})
    await state.set_state(MailingStates.waiting_test_recipients)
    await callback.message.answer("Укажи ID через запятую или напиши «мне», чтобы отправить только администратору.")


@router.callback_query(MailingStates.choosing_mode, F.data == "mailing_mode_full")
@admin_only
async def mailing_mode_full(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"mode": "full"})
    await state.set_state(MailingStates.waiting_schedule)
    await callback.message.answer("Когда отправить? Напиши «сейчас» или дату в формате YYYY-MM-DD HH:MM.")


async def _send_mailing(
    bot,
    *,
    segment: str,
    text: str,
    photo_id: Optional[str],
    buttons: List[dict],
    recipients: Iterable[int],
    test_run: bool,
):
    builder = InlineKeyboardBuilder()
    for button in buttons[:3]:
        builder.add(InlineKeyboardButton(text=button["text"], url=button["url"]))
    builder.add(InlineKeyboardButton(text="Отписаться от рассылки", callback_data="mailing_unsubscribe"))
    reply_markup = builder.as_markup()
    mailing_id = storage.create_mailing(
        segment=segment,
        text=text,
        buttons=buttons,
        image_file_id=photo_id,
        scheduled_at=None,
        test_run=test_run,
    )
    delivered = failed = 0
    for user_id in recipients:
        try:
            if photo_id:
                await bot.send_photo(user_id, photo_id, caption=text, parse_mode="HTML", reply_markup=reply_markup)
            else:
                await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=reply_markup)
            delivered += 1
            storage.log_mailing_delivery(mailing_id, user_id, "delivered")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            storage.log_mailing_delivery(mailing_id, user_id, f"failed:{exc.__class__.__name__}")
        await asyncio.sleep(0.05)
    storage.update_mailing_stats(mailing_id, delivered_delta=delivered, failed_delta=failed)
    summary = f"Рассылка AIVADOG отправлена: {delivered + failed} пользователей, доставлено {delivered}, отклонено {failed}."
    await bot.send_message(ADMIN_ID, summary)


@router.message(MailingStates.waiting_test_recipients)
@admin_only
async def mailing_test_recipients(message: Message, state: FSMContext):
    data = await state.get_data()
    recipients_text = message.text.strip().lower()
    if recipients_text == "мне":
        recipients = [ADMIN_ID]
    else:
        recipients = [int(part.strip()) for part in recipients_text.split(",") if part.strip().isdigit()]
        if not recipients:
            await message.answer("Не удалось распознать ID. Попробуй снова или напиши «мне».")
            return
    await _send_mailing(
        message.bot,
        segment=f"test:{data['segment']}",
        text=data["text"],
        photo_id=data.get("photo_id"),
        buttons=data.get("buttons", []),
        recipients=recipients,
        test_run=True,
    )
    await message.answer("Тестовая рассылка отправлена.")
    await state.clear()


def _parse_datetime(value: str) -> Optional[datetime]:
    value = value.strip()
    if value.lower() == "сейчас":
        return datetime.utcnow()
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


@router.message(MailingStates.waiting_schedule)
@admin_only
async def mailing_schedule(message: Message, state: FSMContext):
    target_time = _parse_datetime(message.text)
    if not target_time:
        await message.answer("Не удалось распознать дату. Используй формат YYYY-MM-DD HH:MM или «сейчас».")
        return
    data = await state.get_data()
    rows = storage.list_users_for_segment(data["segment"])
    recipients = [row["tg_id"] for row in rows]
    if not recipients:
        await message.answer("Нет пользователей в выбранном сегменте.")
        await state.clear()
        return
    delay = max(0, (target_time - datetime.utcnow()).total_seconds())

    async def delayed_send():
        await asyncio.sleep(delay)
        await _send_mailing(
            message.bot,
            segment=data["segment"],
            text=data["text"],
            photo_id=data.get("photo_id"),
            buttons=data.get("buttons", []),
            recipients=recipients,
            test_run=False,
        )

    asyncio.create_task(delayed_send())
    await message.answer("Рассылка будет отправлена по расписанию.")
    await state.clear()