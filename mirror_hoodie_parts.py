from pathlib import Path
from PIL import Image

BASE = Path("/home/user/PycharmProjects/dogsPrivate/templates/одежда_png")

FILES = [
    ("hoodie_left_hood.png",  "hoodie_right_hood.png"),
    ("hoodie_left_sleeve.png", "hoodie_right_sleeve.png"),
]

for src_name, dst_name in FILES:
    src = BASE / src_name
    dst = BASE / dst_name

    if not src.exists():
        print(f"Не найден файл: {src}")
        continue

    img = Image.open(src)
    mirrored = img.transpose(Image.FLIP_LEFT_RIGHT)
    mirrored.save(dst, "PNG")
    print(f"Сохранено: {dst}")