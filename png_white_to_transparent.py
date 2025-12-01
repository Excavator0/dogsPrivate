from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image


def iter_png_files(root: Path) -> Iterable[Path]:
    """
    Возвращает все PNG-файлы по пути:
    - если передан файл, вернёт только его,
    - если папка — обойдёт рекурсивно.
    """
    if root.is_file():
        if root.suffix.lower() == ".png":
            yield root
        return
    for path in sorted(root.rglob("*.png")):
        if path.is_file():
            yield path


def make_white_transparent(path: Path, out_dir: Path | None = None) -> Path:
    """
    Делает строго белый фон (#FFFFFF) прозрачным в одном PNG.
    Никаких допусков: только R=255, G=255, B=255.
    """
    img = Image.open(path).convert("RGBA")
    arr = np.array(img, dtype=np.uint8)  # H x W x 4

    rgb = arr[..., :3]
    white_mask = (
        (rgb[:, :, 0] == 255)
        & (rgb[:, :, 1] == 255)
        & (rgb[:, :, 2] == 255)
    )

    # белые пиксели делаем полностью прозрачными
    arr[white_mask, 3] = 0

    out_dir = out_dir or path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / path.name
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Заменяет строго белый цвет (#FFFFFF) на прозрачный в PNG.\n"
            "Полезно, если фон в макете белый, а должен быть прозрачным."
        )
    )
    parser.add_argument(
        "input",
        help="Путь к PNG или папке с PNG (обработка рекурсивно)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Папка для сохранения (по умолчанию — перезапись в тех же папках)",
    )
    args = parser.parse_args()

    root = Path(args.input).resolve()
    out_root = Path(args.output).resolve() if args.output else None

    if not root.exists():
        raise SystemExit(f"Путь не найден: {root}")

    files = list(iter_png_files(root))
    if not files:
        print(f"PNG-файлы не найдены по пути: {root}")
        return

    print(f"Найдено файлов: {len(files)}")
    for img_path in files:
        if out_root and root.is_dir():
            rel = img_path.relative_to(root).parent
            out_dir = out_root / rel
        else:
            out_dir = out_root or img_path.parent
        out_path = make_white_transparent(img_path, out_dir)
        print(f"[OK] {img_path} -> {out_path}")


if __name__ == "__main__":
    main()


