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
    "hoodie_front": [(380, 480), (1120, 480), (1050, 1350), (450, 1350)],
    "hoodie_back": [(330, 420), (1170, 420), (1100, 1400), (400, 1400)],
    "hoodie_sleeve_left": [(80, 280), (420, 320), (380, 980), (120, 940)],
    "hoodie_sleeve_right": [(80, 320), (420, 280), (380, 940), (120, 980)],
    "hoodie_hood": [(280, 180), (720, 180), (700, 580), (300, 580)],
    
    # Свитшот
    "sweatshirt_front": [(450, 830), (880, 830), (1050, 1350), (450, 1350)],
    "sweatshirt_back": [(330, 420), (1170, 420), (1100, 1400), (400, 1400)],
    "sweatshirt_sleeve_left": [(80, 280), (420, 320), (380, 980), (120, 940)],
    "sweatshirt_sleeve_right": [(80, 320), (420, 280), (380, 940), (120, 980)],
    
    # Футболка
    "shirt_front": [(380, 480), (1120, 480), (1050, 1280), (450, 1280)],
    "shirt_back": [(330, 420), (1170, 420), (1100, 1300), (400, 1300)],
    "shirt_sleeve_left": [(80, 380), (360, 400), (330, 780), (100, 760)],
    "shirt_sleeve_right": [(80, 400), (360, 380), (330, 760), (100, 780)],
    
    # Штаны
    "pants_front": [(280, 380), (1220, 380), (1180, 1580), (320, 1580)],
    "pants_back": [(280, 380), (1220, 380), (1180, 1580), (320, 1580)],
    "pants_pant_left": [(180, 480), (720, 480), (680, 1480), (220, 1480)],
    "pants_pant_right": [(780, 480), (1320, 480), (1280, 1480), (820, 1480)],
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
        if zone in ("sleeve_left", "sleeve_right", "hood", "pant_left", "pant_right"):
            key = f"{base_item}_{zone}"
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

