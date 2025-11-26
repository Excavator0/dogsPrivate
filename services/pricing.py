from __future__ import annotations

from typing import Dict, List, Tuple

DEFAULT_PRICING: Dict[str, int] = {
    "base": 4500,
    "photo": 800,
    "sticker": 300,
}


def calculate_order_price(state_data: Dict, discount_percent: int = 0, pricing: Dict[str, int] | None = None) -> Dict:
    cfg = pricing or DEFAULT_PRICING
    total = cfg["base"]
    addons: List[Tuple[str, int]] = []

    customization = state_data.get("customization", "photo")

    # Проверяем, есть ли вообще активный принт (не удалённый) —
    # если пользователь удалил принт на всех сторонах, не берём оплату за фото.
    has_active_print = False
    positions = state_data.get("pos")
    if isinstance(positions, list):
        for pos in positions:
            if isinstance(pos, list) and pos and pos[0] != -1:
                has_active_print = True
                break

    photo_count = state_data.get("applied_photos", 0)
    if has_active_print and customization in {"ready", "photo", "stickers"}:
        photo_count += 1
    if photo_count:
        if customization == "ready":
            title = "Готовый дизайн AIVADOG (с фото питомца)"
        else:
            title = "Доп. элементы (фото питомца)"
        if photo_count > 1:
            title = f"{title} ×{photo_count}"
        addon_cost = cfg["photo"] * photo_count
        addons.append((title, addon_cost))
        total += addon_cost

    sticker_count = len(state_data.get("applied_stickers", [])) + len(state_data.get("stickers", []))
    if sticker_count:
        addon_cost = sticker_count * cfg["sticker"]
        addons.append((f"Стикеры ×{sticker_count}", addon_cost))
        total += addon_cost

    discount_value = 0
    if discount_percent:
        discount_value = round(total * discount_percent / 100)
        total -= discount_value

    return {
        "base": cfg["base"],
        "addons": addons,
        "discount_percent": discount_percent,
        "discount_value": discount_value,
        "total": total,
    }


def build_price_message(price: Dict) -> str:
    lines = ["💰 Расчёт стоимости:", f"— Базовая цена: {price['base']} ₽"]
    for title, value in price["addons"]:
        lines.append(f"— {title}: +{value} ₽")
    if price["discount_value"]:
        lines.append(f"— Скидка ({price['discount_percent']}%): −{price['discount_value']} ₽")
    lines.append(f"— Итог: <b>{price['total']} ₽</b>")
    return "\n".join(lines)

