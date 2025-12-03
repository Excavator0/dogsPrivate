from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Tuple

import numpy as np
from PIL import Image


def iter_images(paths: Iterable[str]) -> Iterable[Path]:
    """
    Принимает список путей (файлы или папки) и
    возвращает все найденные PNG‑файлы.
    """
    for raw in paths:
        p = Path(raw).resolve()
        if not p.exists():
            print(f"[WARN] Путь не найден: {p}")
            continue
        if p.is_file():
            if p.suffix.lower() == ".png":
                yield p
            else:
                print(f"[WARN] Файл не PNG, пропускаю: {p}")
            continue
        # папка: ищем рекурсивно
        for img in sorted(p.rglob("*.png")):
            if img.is_file():
                yield img


def _alpha_stats(alpha: np.ndarray) -> Tuple[int, int, np.ndarray, np.ndarray]:
    """Возвращает min/max и первые уникальные значения альфы с частотами."""
    a_min = int(alpha.min())
    a_max = int(alpha.max())
    uniq, counts = np.unique(alpha, return_counts=True)
    return a_min, a_max, uniq, counts


def analyze_image(path: Path, save_npy: bool = False, limit_unique: int = 32) -> None:
    """
    Печатает подробную информацию об изображении:
    - размер, режим, формат;
    - наличие альфа‑канала и статистику по нему;
    - статистику по RGB для прозрачных / полупрозрачных пикселей.

    При save_npy=True сохраняет полный numpy‑массив рядом с файлом.
    """
    print("=" * 80)
    print(f"Файл: {path}")

    img = Image.open(path)
    print(f"  Формат: {img.format}, режим: {img.mode}, размер: {img.size[0]}x{img.size[1]}")
    if img.info:
        info_keys = ", ".join(sorted(img.info.keys()))
        print(f"  info.keys: {info_keys or '—'}")
        if "transparency" in img.info:
            print(f"  transparency: {img.info['transparency']!r}")

    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.uint8)  # H x W x 4
    h, w, c = arr.shape
    print(f"  numpy.shape: {arr.shape}, dtype: {arr.dtype}")

    rgb = arr[..., :3]
    alpha = arr[..., 3]

    a_min, a_max, uniq, counts = _alpha_stats(alpha)
    print(f"  Альфа: min={a_min}, max={a_max}, уникальных значений={len(uniq)}")
    for v, cnt in zip(uniq[:limit_unique], counts[:limit_unique]):
        print(f"    alpha={int(v):3d}: {int(cnt)} px")
    if len(uniq) > limit_unique:
        print(f"    ... ещё {len(uniq) - limit_unique} значений альфы опущено")

    # Статистика по полностью прозрачным пикселям (alpha == 0)
    mask_zero = alpha == 0
    zero_count = int(mask_zero.sum())
    print(f"  Прозрачные пиксели (alpha=0): {zero_count}")
    if zero_count:
        rgb_zero = rgb[mask_zero]
        r_min, g_min, b_min = rgb_zero.min(axis=0)
        r_max, g_max, b_max = rgb_zero.max(axis=0)
        print(f"    RGB в alpha=0: R[{r_min},{r_max}] G[{g_min},{g_max}] B[{b_min},{b_max}]")

    # Статистика по полностью непрозрачным пикселям (alpha=255)
    mask_full = alpha == 255
    full_count = int(mask_full.sum())
    print(f"  Непрозрачные пиксели (alpha=255): {full_count}")
    if full_count:
        rgb_full = rgb[mask_full]
        r_min, g_min, b_min = rgb_full.min(axis=0)
        r_max, g_max, b_max = rgb_full.max(axis=0)
        print(f"    RGB в alpha=255: R[{r_min},{r_max}] G[{g_min},{g_max}] B[{b_min},{b_max}]")

    # Полупрозрачные
    mask_mid = (alpha > 0) & (alpha < 255)
    mid_count = int(mask_mid.sum())
    print(f"  Полупрозрачные пиксели (0 < alpha < 255): {mid_count}")
    if mid_count:
        rgb_mid = rgb[mask_mid]
        r_min, g_min, b_min = rgb_mid.min(axis=0)
        r_max, g_max, b_max = rgb_mid.max(axis=0)
        print(f"    RGB в полупрозрачных: R[{r_min},{r_max}] G[{g_min},{g_max}] B[{b_min},{b_max}]")

    if save_npy:
        npy_path = path.with_suffix(path.suffix + ".npy")
        np.save(npy_path, arr)
        print(f"  Полный numpy‑массив сохранён в: {npy_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Отладка PNG: вывод numpy‑массива и статистики по альфа‑каналу.\n"
            "Удобно для сравнения макетов, у которых в Telegram фон ведёт себя по‑разному."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Пути к PNG‑файлам или папкам (можно несколько)",
    )
    parser.add_argument(
        "--save-npy",
        action="store_true",
        help="Сохранять полный numpy‑массив рядом с изображениями (*.npy)",
    )
    args = parser.parse_args()

    files = list(iter_images(args.paths))
    if not files:
        print("PNG‑файлы не найдены.")
        return

    for img_path in files:
        analyze_image(img_path, save_npy=args.save_npy)


if __name__ == "__main__":
    main()




