from __future__ import annotations

from typing import Dict, List, Tuple

DEFAULT_PRICING: Dict[str, int] = {
    "base": 4500,
    "photo": 800,
    "ready_design": 800,
    "sticker": 300,
}


def calculate_order_price(state_data: Dict, discount_percent: int = 0, pricing: Dict[str, int] | None = None) -> Dict:
    cfg = pricing or DEFAULT_PRICING
    total = cfg["base"]
    addons: List[Tuple[str, int]] = []

    # Собираем данные из zone_prints (архивированные зоны)
    zone_prints = state_data.get("zone_prints") or {}
    
    # Подсчитываем количество фото и дизайнов из списка prints
    photo_count = 0
    ready_design_count = 0
    sticker_count = 0
    
    for zone_code, zone_data in zone_prints.items():
        # Новый формат: список принтов
        prints = zone_data.get("prints", [])
        
        # Если нет prints, проверяем старый формат
        if not prints:
            cust = zone_data.get("customization", "photo")
            pos = zone_data.get("pos", [-1, -1])
            has_print = isinstance(pos, list) and pos[0] != -1
            if has_print:
                if cust == "ready":
                    ready_design_count += 1
                else:
                    photo_count += 1
        else:
            # Считаем по списку принтов
            for p in prints:
                cust = p.get("customization", "photo")
                if cust == "ready":
                    ready_design_count += 1
                else:
                    photo_count += 1
        
        # Считаем стикеры по sticker_items (точное количество)
        zone_sticker_items = zone_data.get("sticker_items", [])
        sticker_count += len(zone_sticker_items)
    
    # Добавляем доплату за фото питомца
    if photo_count:
        title = "Фото питомца"
        if photo_count > 1:
            title = f"{title} ×{photo_count}"
        addon_cost = cfg["photo"] * photo_count
        addons.append((title, addon_cost))
        total += addon_cost
    
    # Добавляем доплату за готовые дизайны
    if ready_design_count:
        title = "Готовый дизайн AIVADOG (с фото питомца)"
        if ready_design_count > 1:
            title = f"Готовый дизайн AIVADOG ×{ready_design_count}"
        addon_cost = cfg.get("ready_design", cfg["photo"]) * ready_design_count
        addons.append((title, addon_cost))
        total += addon_cost

    # Подсчитываем стикеры
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

