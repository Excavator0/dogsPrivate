import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, ImageChops
import cv2
from io import BytesIO
from aiogram.types import BufferedInputFile
import rembg
import numpy
import calculate_shades

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


def change_print_shade(image, item):
    """
    Быстрая векторизованная версия применения оттенков по предрасчитанной карте.
    Значительно быстрее прежнего построчного цикла.
    """
    img_rgb = image.convert("RGB")
    np_img = numpy.array(img_rgb, dtype=numpy.uint8)  # H x W x 3
    height, width, _ = np_img.shape
    shade_codes = calculate_shades.arrs.get(item)
    if shade_codes is None or len(shade_codes) != height * width:
        return image

    codes = numpy.array(shade_codes, dtype=numpy.uint8).reshape(height, width)  # H x W
    # Используем расширенный тип, чтобы избежать переполнений при умножении
    result = np_img.astype(numpy.uint16)

    mask_light = codes == 1
    if mask_light.any():
        result[mask_light] = (result[mask_light] * lighter_shade_factor).clip(0, 255)

    mask_shade = codes == 2
    if mask_shade.any():
        result[mask_shade] = (result[mask_shade] * shade_factor).clip(0, 255)

    mask_black = codes == 3
    if mask_black.any():
        result[mask_black] = 0

    out = result.astype(numpy.uint8)
    return Image.fromarray(out, mode="RGB")


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


def paste(image, color, pos, item, side, angle, bg_deleted=False, zone=None):
    base_item, _ = _split_item_code(item)
    template_path = _resolve_template_path(item, side)
    template = Image.open(template_path).convert("RGBA")

    mask_path = MASKS_DIR / f"mask_{base_item}_{'front' if side == 0 else 'back'}.png"
    mask = Image.open(mask_path).convert("L") if mask_path.exists() else None
    
    # Создаем дополнительную маску для ограничения области принта
    from print_bounds import get_print_bounds, create_quad_mask
    bounds_quad = get_print_bounds(item, side, zone)
    if bounds_quad:
        bounds_mask = create_quad_mask(template.size, bounds_quad)
        # Если есть основная маска одежды, объединяем её с маской области
        if mask is not None:
            from PIL import ImageChops
            mask = ImageChops.darker(mask, bounds_mask)
        else:
            mask = bounds_mask

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

# img = paste(None, (176, 37, 37), (0, 0), "cup", 0, 0)
# img.show()

# mask = calculate_outline("cup_front")
# mask.save(f"templates/masks/mask_cup_front.png", "PNG")

# generate_masks_for_clothes()