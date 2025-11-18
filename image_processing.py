import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps
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


def change_print_shade(image, item):
    img = image.convert("RGB")
    d = img.getdata()
    array = calculate_shades.arrs.get(item)
    if array is None or len(array) != len(d):
        return image

    new_image = []
    for i in range(len(d)):
        if array[i] == 1:
            new_image.append(
                (
                    int(d[i][0] * lighter_shade_factor),
                    int(d[i][1] * lighter_shade_factor),
                    int(d[i][2] * lighter_shade_factor),
                )
            )
        elif array[i] == 2:
            new_image.append(
                (int(d[i][0] * shade_factor), int(d[i][1] * shade_factor), int(d[i][2] * shade_factor))
            )
        elif array[i] == 3:
            new_image.append((0, 0, 0))
        else:
            new_image.append(d[i])

    img.putdata(new_image)

    return img


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


def paste(image, color, pos, item, side, angle, bg_deleted=False):
    base_item, _ = _split_item_code(item)
    template_path = _resolve_template_path(item, side)
    template = Image.open(template_path).convert("RGBA")

    mask_path = MASKS_DIR / f"mask_{base_item}_{'front' if side == 0 else 'back'}.png"
    mask = Image.open(mask_path).convert("L") if mask_path.exists() else None

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

    shade_key = f"{base_item}_{'front' if side == 0 else 'back'}"
    result = change_print_shade(result, shade_key)
    return result


def image_to_bytes(template):
    bio = BytesIO()
    bio.name = "name.png"
    template.save(bio, "PNG")
    bio.seek(0)
    file = BufferedInputFile(bio.getvalue(), filename="name.png")
    return file


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