import json

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


def change_print_shade(image, item):
    img = image.convert("RGB")

    d = img.getdata()
    new_image = []
    array = calculate_shades.arrs.get(item)
    for i in range(len(d)):
        if array[i] == 1:
            new_image.append((int(d[i][0] * lighter_shade_factor), int(d[i][1] * lighter_shade_factor),
                              int(d[i][2] * lighter_shade_factor)))
        elif array[i] == 2:
            new_image.append((int(d[i][0] * shade_factor), int(d[i][1] * shade_factor),
                              int(d[i][2] * shade_factor)))
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


def paste(image, color, pos, item, side, angle, bg_deleted=False):
    color = tuple(color)

    if side == 0:
        item = item + "_front"
    else:
        item = item + "_back"
    template = Image.open(f"templates/{item}.png").convert("RGBA")
    mask = Image.open(f"templates/masks/mask_{item}.png")
    rgba_color = color + (255,)
    temporary_image = Image.new("RGBA", mask.size, rgba_color)
    if 'A' in template.mode:
        # Extract the alpha channel and invert it
        alpha = template.getchannel('A')
        alpha = ImageOps.invert(alpha)
        # Paste white onto image wherever it is transparent
        template.paste((255, 255, 255), mask=alpha)
    # editing image
    if image is not None:
        if angle != 0:
            image = image.rotate(angle, expand=True)
        image = image.convert("RGBA")

        # pasting onto template
        if pos != "deleted":
            pos = tuple(pos)
            temporary_image.paste(image, pos, image)

    template.paste(temporary_image, (0, 0), mask)
    if item == "bag_front" or item == "bag_back" or item == "cap_back":
        mask = Image.open(f"templates/masks/{item}_hole.png").convert("L")
        only_color = Image.new("RGBA", mask.size, (255, 255, 255, 255))
        template.paste(only_color, (0, 0), mask)
    template = change_print_shade(template, item)
    return template


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

img = paste(None, (176, 37, 37), (0, 0), "cup", 0, 0)
img.show()

# mask = calculate_outline("cup_front")
# mask.save(f"templates/masks/mask_cup_front.png", "PNG")