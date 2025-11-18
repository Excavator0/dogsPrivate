from __future__ import annotations

from pathlib import Path
from typing import Dict

import numpy
from PIL import Image

TEMPLATES_DIR = Path("templates") / "одежда_png"


def _resolve_template(item: str, side: int) -> Path:
    side_name = "front" if side == 0 else "back"
    candidates = []
    if item == "shirt":
        candidates.append(TEMPLATES_DIR / f"{item}_{side_name}_black.png")
    candidates.append(TEMPLATES_DIR / f"{item}_{side_name}.png")
    candidates.append(Path("templates") / f"{item}_{side_name}.png")
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"Не найден шаблон для {item}_{side_name}")


def generate_shade_array(item: str, side: int):
    img = Image.open(_resolve_template(item, side)).convert("RGB")
    d = img.getdata()
    shade_array = []
    # 0 - plain color, 1 - lighter shade, 2 - shade, 3 - outline
    for pixel in d:
        if pixel[0] in range(240, 256):
            shade_array.append(0)
        elif pixel[0] in range(220, 240):
            shade_array.append(1)
        elif pixel[0] in range(45, 220):
            shade_array.append(2)
        else:
            shade_array.append(3)
    return numpy.array(shade_array)


arrs: Dict[str, numpy.ndarray] = {}
for side in (0, 1):
    try:
        key = f"shirt_{'front' if side == 0 else 'back'}"
        arrs[key] = generate_shade_array("shirt", side)
    except FileNotFoundError:
        continue
