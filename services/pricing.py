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

    if state_data.get("customization", "photo") in {"ready", "photo", "stickers"}:
        addons.append(("Доп. элементы (фото питомца)", cfg["photo"]))
        total += cfg["photo"]

    sticker_count = len(state_data.get("stickers", []))
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

