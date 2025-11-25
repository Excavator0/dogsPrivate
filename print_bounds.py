"""
Конфигурация допустимых областей для размещения принтов на одежде.
Каждая область задается четырехугольником произвольной формы.
Формат: [(x1, y1), (x2, y2), (x3, y3), (x4, y4)]
где точки идут по часовой стрелке: верхний левый, верхний правый, нижний правый, нижний левый
"""

# Словарь границ для каждого типа одежды и стороны
# Ключ: "{тип_одежды}_{сторона}" (например, "hoodie_front", "hoodie_back")
# Значение: список из 4 точек (x, y) по часовой стрелке
PRINT_BOUNDS = {

    # Худи
    # Область спины (трапеция - уже внизу, шире вверху у плеч)
    "hoodie_front": [(473, 821), (913, 821), (913, 1353), (473, 1353)],
    "hoodie_back": [(581, 946), (1144, 946), (1144, 2084), (581, 2084)],
    "hoodie_sleeve_left": [(537, 1348), (866, 1348), (866, 2050), (537, 2050)],
    "hoodie_sleeve_right": [(730, 1280), (1040, 1280), (1040, 2700), (730, 2700)],
    "hoodie_hood_left": [(634, 307), (1149, 307), (1149, 1040), (634, 1040)],
    "hoodie_hood_right": [(500, 340), (1080, 340), (1080, 1100), (500, 1100)],

    # Свитшот
    "sweatshirt_front": [(336, 400), (898, 400), (898, 1273), (336, 1273)],
    "sweatshirt_back": [(384, 317), (1170, 317), (877, 1236), (384, 1236)],
    "sweatshirt_sleeve_left": [(870, 979), (1199, 979), (1199, 2226), (870, 2226)],
    "sweatshirt_sleeve_right": [(778, 876), (1014, 876), (1014, 2097), (778, 2097)],
    
    # Футболка
    "shirt_front": [(2058, 1517), (3317, 1517), (3317, 4233), (2058, 4233)],
    "shirt_back": [(2048, 1351), (3357, 1351), (3357, 4185), (2048, 4185)],
    
    # Штаны
    # Перед / зад — левая / правая штанина (координаты примерные, уточните под шаблоны)
    "pants_pant_front_left": [(88, 250), (440, 250), (440, 2437), (88, 2437)],
    "pants_pant_front_right": [(630, 250), (990, 250), (990, 2437), (630, 2437)],
    "pants_pant_back_left": [(105, 300), (440, 300), (440, 2437), (105, 2437)],
    "pants_pant_back_right": [(630, 300), (975, 300), (975, 2437), (630, 2437)],
}


def get_print_bounds(item_code: str, side: int, zone: str = None) -> list[tuple[int, int]] | None:
    """
    Получить границы допустимой области для принта.
    
    Args:
        item_code: Код изделия (например, "hoodie", "hoodie_black", "shirt_pink")
        side: Сторона (0 = front, 1 = back)
        zone: Зона нанесения (например, "chest", "back", "sleeve_left", "hood", "pant_left")
    
    Returns:
        Список из 4 точек [(x1,y1), (x2,y2), (x3,y3), (x4,y4)] или None, если границы не заданы
    """
    # Извлекаем базовый тип изделия (без цвета)
    base_item = item_code.split("_")[0]
    
    # Определяем ключ для поиска границ
    if zone:
        # Если указана зона (рукав, капюшон, штанина), используем её
        if zone in ("sleeve_left", "sleeve_right", "hood", "hood_left", "hood_right", "pant_left", "pant_right") or zone.startswith(
            "pant_"
        ):
            # Поддерживаем несколько вариантов ключей для капюшона
            if zone == "hood":
                candidates = [
                    f"{base_item}_hood",
                    f"{base_item}_hood_left",
                    f"{base_item}_hood_right",
                ]
                key = next((k for k in candidates if k in PRINT_BOUNDS), None)
                if key is None:
                    return None
            elif zone in ("pant_left", "pant_right"):
                # Старые коды штанин мапим на передние зоны
                mapped = "pant_front_left" if zone == "pant_left" else "pant_front_right"
                key = f"{base_item}_{mapped}"
                if key not in PRINT_BOUNDS:
                    return None
            else:
                key = f"{base_item}_{zone}"
                if key not in PRINT_BOUNDS:
                    return None
        else:
            # Для chest, back и других основных зон используем сторону
            side_name = "front" if side == 0 else "back"
            key = f"{base_item}_{side_name}"
    else:
        # Если зона не указана, используем только сторону
        side_name = "front" if side == 0 else "back"
        key = f"{base_item}_{side_name}"
    
    return PRINT_BOUNDS.get(key)


def _get_quad_bounding_box(quad: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    """
    Получить ограничивающий прямоугольник для четырехугольника.
    
    Args:
        quad: Список из 4 точек
        
    Returns:
        (x_min, y_min, x_max, y_max)
    """
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return (min(xs), min(ys), max(xs), max(ys))


def clamp_position(
    print_x: int, 
    print_y: int, 
    print_width: int, 
    print_height: int,
    bounds: list[tuple[int, int]]
) -> tuple[int, int]:
    """
    Ограничить позицию принта так, чтобы он полностью находился в пределах допустимой области.
    Для четырехугольника произвольной формы используем ограничивающий прямоугольник.
    
    Args:
        print_x: X координата левого верхнего угла принта
        print_y: Y координата левого верхнего угла принта
        print_width: Ширина принта
        print_height: Высота принта
        bounds: Четырехугольник из 4 точек [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    
    Returns:
        Скорректированные координаты (x, y)
    """
    x_min, y_min, x_max, y_max = _get_quad_bounding_box(bounds)
    
    # Ограничиваем X
    clamped_x = max(x_min, min(print_x, x_max - print_width))
    
    # Ограничиваем Y
    clamped_y = max(y_min, min(print_y, y_max - print_height))
    
    return (clamped_x, clamped_y)


def is_position_valid(
    print_x: int,
    print_y: int,
    print_width: int,
    print_height: int,
    bounds: list[tuple[int, int]]
) -> bool:
    """
    Проверить, находится ли принт полностью в пределах допустимой области.
    Для четырехугольника произвольной формы используем ограничивающий прямоугольник.
    
    Args:
        print_x: X координата левого верхнего угла принта
        print_y: Y координата левого верхнего угла принта
        print_width: Ширина принта
        print_height: Высота принта
        bounds: Четырехугольник из 4 точек [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    
    Returns:
        True, если принт полностью в пределах области
    """
    x_min, y_min, x_max, y_max = _get_quad_bounding_box(bounds)
    
    # Проверяем, что все углы принта находятся в пределах области
    return (
        print_x >= x_min and
        print_y >= y_min and
        print_x + print_width <= x_max and
        print_y + print_height <= y_max
    )


def get_centered_position_in_bounds(
    print_width: int,
    print_height: int,
    bounds: list[tuple[int, int]]
) -> tuple[int, int]:
    """
    Получить центрированную позицию принта в пределах допустимой области.
    Для четырехугольника произвольной формы используем центр ограничивающего прямоугольника.
    
    Args:
        print_width: Ширина принта
        print_height: Высота принта
        bounds: Четырехугольник из 4 точек [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    
    Returns:
        Координаты (x, y) для центрированного размещения
    """
    x_min, y_min, x_max, y_max = _get_quad_bounding_box(bounds)
    
    # Вычисляем центр области
    center_x = (x_min + x_max) // 2
    center_y = (y_min + y_max) // 2
    
    # Вычисляем позицию так, чтобы центр принта совпадал с центром области
    pos_x = center_x - print_width // 2
    pos_y = center_y - print_height // 2
    
    # На всякий случай применяем clamp
    return clamp_position(pos_x, pos_y, print_width, print_height, bounds)


def create_quad_mask(template_size: tuple[int, int], quad: list[tuple[int, int]]):
    """
    Создать маску из четырехугольника для ограничения области принта.
    
    Args:
        template_size: Размер шаблона (width, height)
        quad: Четырехугольник из 4 точек [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    
    Returns:
        PIL Image в режиме "L" (grayscale) - белый внутри четырехугольника, черный снаружи
    """
    from PIL import Image, ImageDraw
    
    mask = Image.new("L", template_size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(quad, fill=255)
    return mask

