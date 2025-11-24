from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

EXPORT_DIR = Path("exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def generate_users_excel(rows: Sequence) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Пользователи"
    headers = [
        "ID",
        "Username",
        "Имя",
        "Телефон",
        "E-mail",
        "Дата регистрации",
        "Последняя активность",
        "Подписан",
        "Есть заказы",
        "Кол-во заказов",
        "Сумма покупок",
    ]
    sheet.append(headers)
    header_font = Font(bold=True)
    for idx, _ in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=idx)
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        sheet.append(
            [
                row["id"],
                row["username"],
                row["full_name"],
                row["phone"],
                row["email"],
                row["first_seen"],
                row["last_active"],
                "Да" if row["is_subscribed"] else "Нет",
                "Да" if row["orders_total"] else "Нет",
                row["orders_total"],
                row["total_orders_sum"],
            ]
        )

    for column in sheet.columns:
        max_length = max(len(str(cell.value)) if cell.value else 0 for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = max(12, min(max_length + 2, 40))

    filename = EXPORT_DIR / f"users_{datetime.utcnow():%Y%m%d_%H%M%S}.xlsx"
    workbook.save(filename)
    return filename




