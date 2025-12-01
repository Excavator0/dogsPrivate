import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, ImageChops
import cv2
from io import BytesIO
from aiogram.types import BufferedInputFile
import rembg
import numpy
from aiogram.utils.mypy_hacks import lru_cache

# import calculate_shades

shade_factor = 0.875
lighter_shade_factor = 0.92


# def generate_shade_array(item, side):
#     if side == 0:
#         side = "front"
#     else:
#         side = "back"
#     img = Image.open(f"templates/{item}_{side}.png")
#     img = img.convert("RGB")
#
#     d = img.getdata()
#     shade_array = []
#
#     # 0 - plain color, 1 - lighter shade, 2 - shade, 3 - outline
#     for item in d:
#
#         # change all white (also shades of whites)
#         if item[0] in list(range(240, 256)):
#             shade_array.append(0)
#         elif item[0] in list(range(220, 240)):
#             shade_array.append(1)
#         elif item[0] in list(range(45, 220)):
#             shade_array.append(2)
#         else:
#             shade_array.append(3)
#
#     shade_array = numpy.array(shade_array)
#     numpy.savez('templates/shades.npz', shade_array)


TEMPLATES_DIR = Path("templates")
CLOTHES_DIR = TEMPLATES_DIR / "одежда_png"
MASKS_DIR = TEMPLATES_DIR / "masks"


def _iter_clothes_assets():
    """
    Сканирует папку с одеждой и собирает пути картинок по base/side.
    Ожидаемые имена файлов:
      - {base}_front.png
      - {base}_back.png
      - {base}_front_{variant}.png
      - {base}_back_{variant}.png
    Возвращает словарь: {(base, side): [Path, ...]}
    """
    side_markers = ("_front", "_back")
    mapping: dict[tuple[str, str], list[Path]] = {}
    if not CLOTHES_DIR.exists():
        return mapping
    for path in CLOTHES_DIR.glob("*.png"):
        name = path.stem  # without .png
        side = None
        base = None
        for marker in side_markers:
            if marker in name:
                side = "front" if marker == "_front" else "back"
                base = name.split(marker, 1)[0]
                break
        if not base or not side:
            continue
        mapping.setdefault((base, side), []).append(path)
    return mapping


def _build_mask_from_images(image_paths: list[Path]) -> Optional[Image.Image]:
    """
    Формирует маску (L) как объединение непрозрачных пикселей по всем вариантам цвета.
    """
    if not image_paths:
        return None
    base_img = Image.open(image_paths[0]).convert("RGBA")
    width, height = base_img.size
    union = Image.new("L", (width, height), 0)

    for path in image_paths:
        img = Image.open(path).convert("RGBA")
        if img.size != (width, height):
            img = img.resize((width, height), Image.Resampling.BICUBIC)
        alpha = img.split()[-1]  # A
        # Считаем пиксель частью одежды, если альфа > ~10
        binary = alpha.point(lambda a: 255 if a > 10 else 0, mode="L")
        union = ImageChops.lighter(union, binary)
    return union


def generate_masks_for_clothes() -> dict:
    """
    Пересоздаёт маски для всех вещей из папки 'templates/одежда_png'.
    1) Очищает 'templates/masks' от старых файлов
    2) Для каждой пары (base, side) создаёт 'mask_{base}_{side}.png'
    Возвращает краткую статистику.
    """
    MASKS_DIR.mkdir(parents=True, exist_ok=True)
    # Удаляем старые маски
    removed = 0
    for old in MASKS_DIR.glob("*.png"):
        old.unlink(missing_ok=True)
        removed += 1

    mapping = _iter_clothes_assets()
    created = 0
    skipped = 0
    results = {}
    for (base, side), paths in mapping.items():
        mask = _build_mask_from_images(paths)
        if not mask:
            skipped += 1
            continue
        out_path = MASKS_DIR / f"mask_{base}_{side}.png"
        mask.save(out_path, "PNG")
        created += 1
        results[f"{base}_{side}"] = str(out_path)

    return {"removed": removed, "created": created, "skipped": skipped, "total_pairs": len(mapping), "outputs": results}


# def change_print_shade(image, item):
#     """
#     Быстрая векторизованная версия применения оттенков по предрасчитанной карте.
#     Значительно быстрее прежнего построчного цикла.
#     """
#     img_rgb = image.convert("RGB")
#     np_img = numpy.array(img_rgb, dtype=numpy.uint8)  # H x W x 3
#     height, width, _ = np_img.shape
#     shade_codes = calculate_shades.arrs.get(item)
#     if shade_codes is None or len(shade_codes) != height * width:
#         return image
#
#     codes = numpy.array(shade_codes, dtype=numpy.uint8).reshape(height, width)  # H x W
#     # Используем расширенный тип, чтобы избежать переполнений при умножении
#     result = np_img.astype(numpy.uint16)
#
#     mask_light = codes == 1
#     if mask_light.any():
#         result[mask_light] = (result[mask_light] * lighter_shade_factor).clip(0, 255)
#
#     mask_shade = codes == 2
#     if mask_shade.any():
#         result[mask_shade] = (result[mask_shade] * shade_factor).clip(0, 255)
#
#     mask_black = codes == 3
#     if mask_black.any():
#         result[mask_black] = 0
#
#     out = result.astype(numpy.uint8)
#     return Image.fromarray(out, mode="RGB")


def calculate_outline(item):
    img = cv2.imread(f"templates/{item}.png")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(gray, 0, 20)

    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    y_threshold = 200
    filtered_contours = []
    for contour in contours:
        # Проверяем, чтобы все точки контура имели x меньше порога
        if all(point[0][1] >= y_threshold for point in contour):
            filtered_contours.append(contour)

    mask[:] = 0
    for con in filtered_contours:
        mask = cv2.drawContours(mask, [con], -1, (255, 255, 255), -1)

    img[mask != 255] = (255, 255, 255)
    mask = Image.fromarray(mask)
    mask.convert("RGB")
    return mask


def _split_item_code(item_code: str) -> tuple[str, Optional[str]]:
    parts = item_code.split("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return item_code, None


def _resolve_template_path(item_code: str, side: int) -> Path:
    base_item, variant = _split_item_code(item_code)
    side_name = "front" if side == 0 else "back"
    candidates = []
    if variant:
        candidates.append(CLOTHES_DIR / f"{base_item}_{side_name}_{variant}.png")
        candidates.append(CLOTHES_DIR / f"{item_code}_{side_name}.png")
    candidates.append(CLOTHES_DIR / f"{base_item}_{side_name}.png")
    candidates.append(TEMPLATES_DIR / f"{base_item}_{side_name}.png")
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"Не найден макет {item_code} ({side_name})")


def get_template_bounds(item_code: str) -> tuple[int, int]:
    """
    Возвращает размер базового шаблона (front) для изделия.
    Используется как запасной вариант, если маска зоны не найдена.
    """
    template_path = _resolve_template_path(item_code, 0)
    with Image.open(template_path) as template:
        return template.size


def _resolve_template_for_paste(item_code: str, side: int, zone: str | None) -> Path:
    """
    Возвращает путь к нужному макету с учётом зоны (рукав, капюшон и т.п.).
    Для специальных зон худи/свитшота подставляем отдельные шаблоны,
    в остальных случаях используем стандартный front/back.
    """
    base_item, _ = _split_item_code(item_code)

    # Специальные зоны для худи
    if base_item == "hoodie" and zone:
        if zone == "sleeve_left":
            cand = CLOTHES_DIR / "hoodie_left_sleeve.png"
            if cand.exists():
                return cand
        elif zone == "sleeve_right":
            cand = CLOTHES_DIR / "hoodie_right_sleeve.png"
            if cand.exists():
                return cand
        elif zone in ("hood", "hood_left"):
            # для совместимости: общая зона hood и явная hood_left
            for name in ("hoodie_left_hood.png", "hoodie_hood.png"):
                cand = CLOTHES_DIR / name
                if cand.exists():
                    return cand
        elif zone == "hood_right":
            cand = CLOTHES_DIR / "hoodie_right_hood.png"
            if cand.exists():
                return cand

    # Специальные зоны для свитшота (рукава)
    if base_item == "sweatshirt" and zone:
        if zone == "sleeve_left":
            cand = CLOTHES_DIR / "sweatshirt_left_sleeve.png"
            if cand.exists():
                return cand
        elif zone == "sleeve_right":
            cand = CLOTHES_DIR / "sweatshirt_right_sleeve.png"
            if cand.exists():
                return cand

    # По умолчанию — стандартный front/back
    return _resolve_template_path(item_code, side)


def _is_special_zone(zone: str | None) -> bool:
    """
    Проверяет, является ли зона специальной (рукав, капюшон, штанина),
    для которой нужен отдельный шаблон вместо front/back.
    """
    if not zone:
        return False
    special_zones = (
        "sleeve_left", "sleeve_right",
        "hood", "hood_left", "hood_right",
        "pant_front_left", "pant_front_right",
        "pant_back_left", "pant_back_right",
    )
    return zone in special_zones


_ZONE_SUFFIX_MAP = {
    "sleeve_left": "left_sleeve",
    "sleeve_right": "right_sleeve",
    "hood_left": "left_hood",
    "hood_right": "right_hood",
    "hood": "hood",
}


def _resolve_zone_mask_name(item_code: str, side: int, zone: str | None) -> Optional[str]:
    """
    Подбирает имя маски зоны на основе кода изделия и зоны.
    Маски лежат в templates/masks и имеют вид:
      - mask_shirt_front.png
      - mask_shirt_back.png
      - mask_hoodie_left_sleeve.png и т.п.
    """
    base_item, _ = _split_item_code(item_code)
    if not base_item:
        return None
    suffix: Optional[str] = None
    if zone in ("chest", None):
        suffix = "front" if side == 0 else "back"
    elif zone == "back":
        suffix = "back"
    elif zone in _ZONE_SUFFIX_MAP:
        suffix = _ZONE_SUFFIX_MAP[zone]
    elif zone and zone.startswith("pant_"):
        suffix = zone.replace("pant_", "")
    elif zone in ("pant_left", "pant_right"):
        suffix = "front_left" if zone == "pant_left" else "front_right"
    else:
        suffix = "front" if side == 0 else "back"
    return f"{base_item}_{suffix}" if suffix else None


@lru_cache(maxsize=128)
def _load_zone_mask_image(item_code: str, side: int, zone: str | None) -> Optional[Image.Image]:
    """
    Загружает маску зоны как изображение в режиме "L".
    В маске нужная зона чёрная, фон — прозрачный.
    Мы используем альфа-канал как зону (alpha > 0 -> 255, иначе 0).
    """
    mask_name = _resolve_zone_mask_name(item_code, side, zone)
    if not mask_name:
        return None
    mask_path = MASKS_DIR / f"mask_{mask_name}.png"
    if not mask_path.exists():
        return None
    with Image.open(mask_path).convert("RGBA") as img:
        alpha = img.split()[-1]
        binary = alpha.point(lambda a: 255 if a > 0 else 0, mode="L")
        return binary


@lru_cache(maxsize=128)
def _get_zone_mask_bbox(item_code: str, side: int, zone: str | None) -> tuple[int, int, int, int]:
    """
    Возвращает bounding box зоны по маске.
    Если маска не найдена, используется весь шаблон.
    """
    mask = _load_zone_mask_image(item_code, side, zone)
    if mask:
        bbox = mask.getbbox()
        if bbox:
            return bbox
    width, height = get_template_bounds(item_code)
    return (0, 0, width, height)


def _clamp_position_with_mask(
    print_x: int,
    print_y: int,
    print_width: int,
    print_height: int,
    item_code: str,
    side: int,
    zone: Optional[str],
) -> list[int]:
    """
    Ограничивает позицию принта так, чтобы он оставался внутри зоны маски.
    """
    x_min, y_min, x_max, y_max = _get_zone_mask_bbox(item_code, side, zone)
    max_x = x_max - print_width
    max_y = y_max - print_height
    clamped_x = max(x_min, min(print_x, max_x))
    clamped_y = max(y_min, min(print_y, max_y))
    return [int(clamped_x), int(clamped_y)]


def _get_centered_position_in_zone(
    item_code: str,
    side: int,
    zone: Optional[str],
    print_width: int,
    print_height: int,
) -> list[int]:
    """
    Центрирует принт внутри маски зоны.
    """
    x_min, y_min, x_max, y_max = _get_zone_mask_bbox(item_code, side, zone)
    area_width = max(1, x_max - x_min)
    area_height = max(1, y_max - y_min)
    center_x = x_min + area_width // 2
    center_y = y_min + area_height // 2
    pos_x = center_x - print_width // 2
    pos_y = center_y - print_height // 2
    return _clamp_position_with_mask(pos_x, pos_y, print_width, print_height, item_code, side, zone)


def _get_zone_mask_for_overlay(
    item_code: str,
    side: int,
    zone: Optional[str],
    target_size: tuple[int, int],
) -> Optional[Image.Image]:
    """
    Возвращает маску зоны, подогнанную под нужный размер (для наложения принта).
    """
    mask = _load_zone_mask_image(item_code, side, zone)
    if mask and mask.size != target_size:
        mask = mask.resize(target_size, Image.Resampling.NEAREST)
    return mask


def paste(image, color, pos, item, side, angle, bg_deleted=False, zone=None, template_override=None):
    # Для специальных зон (рукав, капюшон) игнорируем template_override,
    # так как он содержит front/back макет, а не шаблон этой зоны
    use_override = template_override and Path(template_override).exists() and not _is_special_zone(zone)
    if use_override:
        template = Image.open(template_override).convert("RGBA")
    else:
        template_path = _resolve_template_for_paste(item, side, zone)
        template = Image.open(template_path).convert("RGBA")

    # Маска зоны для ограничения области принта и перекраски
    mask = _get_zone_mask_for_overlay(item, side, zone, template.size)

    color_layer = None
    if color is not None and mask is not None:
        rgba_color = tuple(color) + (255,)
        color_layer = Image.new("RGBA", template.size, rgba_color)

    work_layer = Image.new("RGBA", template.size, (0, 0, 0, 0))
    if image is not None:
        if angle != 0:
            image = image.rotate(angle, expand=True)
        image = image.convert("RGBA")
        if pos != "deleted":
            work_layer.paste(image, tuple(pos), image)

    if mask is not None:
        masked_layer = Image.new("RGBA", template.size, (0, 0, 0, 0))
        masked_layer.paste(work_layer, (0, 0), mask)
    else:
        masked_layer = work_layer

    result = template.copy()
    if color_layer:
        tinted = Image.new("RGBA", template.size, (0, 0, 0, 0))
        tinted.paste(color_layer, (0, 0), mask)
        result = Image.alpha_composite(result, tinted)
    result = Image.alpha_composite(result, masked_layer)
    return result


def image_to_bytes(template: Image.Image) -> BufferedInputFile:
    """
    Готовит изображение к отправке как фото в Telegram:
    - даунскейлит до лимита по большей стороне (например, 4096)
    - убирает альфу, конвертирует в RGB
    - сохраняет как JPEG (умеренный quality), чтобы избежать ошибок по размеру/альфе
    """
    max_side = 4096
    width, height = template.size
    if width <= 0 or height <= 0:
        # страхуемся от нулевых размеров
        width = max(1, width)
        height = max(1, height)
        template = template.resize((width, height))
    scale = 1.0
    if max(width, height) > max_side:
        scale = max_side / float(max(width, height))
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        template = template.resize(new_size, Image.Resampling.LANCZOS)
    # снимаем альфу
    if template.mode in ("RGBA", "LA"):
        background = Image.new("RGB", template.size, (255, 255, 255))
        background.paste(template, mask=template.split()[-1])
        img = background
    else:
        img = template.convert("RGB")
    bio = BytesIO()
    bio.name = "preview.jpg"
    img.save(bio, "JPEG", quality=90, optimize=True)
    bio.seek(0)
    return BufferedInputFile(bio.getvalue(), filename="preview.jpg")


def image_to_json(image):
    return json.dumps(numpy.array(image).tolist())


def json_to_image(arr):
    return Image.fromarray(numpy.array(json.loads(arr), dtype='uint8'))


def print_remove_bg(image):
    img = rembg.remove(image)
    return img

# def remove_only_white():
#     import numpy as np
#     from PIL import Image
#
#     img = Image.open("templates/одежда_png/pants_front.png").convert("RGBA")
#     arr = np.array(img)
#
#     white = np.all(arr[:, :, :3] == [255, 255, 255], axis=2)
#
#     arr[white, 3] = 0  # делаем прозрачным
#
#     result = Image.fromarray(arr)
#     result.save("templates/pants_front.png")