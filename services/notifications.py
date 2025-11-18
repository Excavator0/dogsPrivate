from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from typing import Optional, Sequence, Tuple

from aiogram import Bot

from database.db import Database
from handlers.order_handlers import order_types

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "false").lower() in {"1", "true", "yes"}
ORDER_EMAIL_TO = os.getenv("ORDER_EMAIL_TO", "aukhadyev.subsid@gmail.com") # "aivadog@yandex.ru" )


async def _download_file(bot: Bot, file_id: str) -> Optional[Tuple[bytes, str]]:
    if not file_id:
        return None
    buffer = await bot.download(file_id)
    buffer.seek(0)
    data = buffer.read()
    filename = f"{file_id}.png"
    return data, filename


def _send_email(subject: str, body: str, attachments: Sequence[Tuple[str, bytes]]):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD):
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_USER
    message["To"] = ORDER_EMAIL_TO
    message.set_content(body)
    for filename, data in attachments:
        message.add_attachment(data, maintype="image", subtype="png", filename=filename)
    if SMTP_USE_TLS:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
    with server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)


async def notify_order_via_email(
    bot: Bot,
    db: Database,
    order_id: int,
    front_id: Optional[str],
    back_id: Optional[str],
    price_total: int,
):
    order = db.get_order_with_user(order_id)
    if not order:
        return
    notes = json.loads(order["notes_json"]) if order.get("notes_json") else {}
    order_label = next((label for label, code in order_types.items() if code == order["item_code"]), order["item_code"])
    subject = f"AIVADOG заказ #{order['order_number']}"
    design_title = notes.get("ready_design_title", "—")
    body = (
        "Новый заказ в AIVADOG:\n"
        f"— Изделие: {order_label}\n"
        f"— Зона: {order['zone']}\n"
        f"— Размер: {order['size']}\n"
        f"— Кастомизация: {order['customization']}\n"
        f"— Дизайн: {design_title}\n"
        f"— Имя питомца: {order['pet_name'] or '—'}\n"
        f"— Стикеры: {order['stickers'] or '[]'}\n"
        f"— Стоимость: {price_total} ₽\n"
        f"— Контакты: {order['contact_phone'] or '—'} / {order['contact_email'] or '—'}\n"
        f"— Клиент: @{order['username'] or '—'}\n"
    )
    attachments: list[Tuple[str, bytes]] = []
    for file_id, suffix in ((front_id, "front"), (back_id, "back")):
        if not file_id:
            continue
        downloaded = await _download_file(bot, file_id)
        if downloaded:
            data, filename_raw = downloaded
            filename = f"{order['order_number']}_{suffix}.jpg"
            attachments.append((filename, data))
    _send_email(subject, body, attachments)

