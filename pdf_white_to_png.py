from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
from pdf2image import convert_from_path
from PIL import Image


def iter_pdf_files(root: Path) -> Iterable[Path]:
    """
    Рекурсивно обходит директорию и возвращает все .pdf файлы.
    Если передан путь к файлу, возвращает только его.
    """
    if root.is_file():
        if root.suffix.lower() == ".pdf":
            yield root
        return
    for path in sorted(root.rglob("*.pdf")):
        if path.is_file():
            yield path


def remove_pure_white_background(img: Image.Image) -> Image.Image:
    """
    Делает чисто белые пиксели (#FFFFFF, без допусков) полностью прозрачными.

    Важно: только точное совпадение (R=255, G=255, B=255). Никаких оттенков.
    """
    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.uint8)  # H x W x 4

    # # Маска строго белых пикселей по RGB
    rgb = arr[..., :3]
    white_mask = (rgb[:, :, 0] == 255) & (rgb[:, :, 1] == 255) & (rgb[:, :, 2] == 255)

    # Обнуляем альфа‑канал только там, где строго #FFFFFF
    arr[white_mask, 3] = 0

    return Image.fromarray(arr, mode="RGBA")


def convert_pdf_to_png_white_bg(
    pdf_path: Path,
    out_dir: Path,
    dpi: int = 300,
    poppler_path: Optional[str] = None,
) -> None:
    """
    Конвертирует один PDF в PNG‑страницы с прозрачным фоном вместо чисто белого.
    """
    kwargs: dict = {"dpi": dpi}
    if poppler_path:
        kwargs["poppler_path"] = poppler_path

    pages = convert_from_path(str(pdf_path), **kwargs)
    if not pages:
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    for idx, page in enumerate(pages, start=1):
        page_rgba = page.convert("RGBA")
        processed = remove_pure_white_background(page_rgba)

        stem = pdf_path.stem if len(pages) == 1 else f"{pdf_path.stem}_{idx}"
        out_path = out_dir / f"{stem}.png"
        processed.save(out_path)
        print(f"[OK] {pdf_path.name} → {out_path.relative_to(out_dir.parent)}")


def main() -> None:
    parser = new_arg_parser()
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_root = Path(args.output).resolve() if args.output else input_path
    poppler_path = args.poppler_path

    if not input_path.exists():
        raise SystemExit(f"Путь не найден: {input_path}")

    pdf_files = list(iter_pdf_files(input_path))
    if not pdf_files:
        print(f"В {input_path} не найдено PDF‑файлов")
        return

    print(f"Найдено файлов: {len(pdf_files)}")
    for pdf in pdf_files:
        # Если вход — директория, сохраняем структуру подпапок
        if input_path.is_dir():
            rel = pdf.relative_to(input_path).with_suffix("")  # без .pdf
            out_dir = output_root / rel.parent
        else:
            out_dir = output_root
        try:
            convert_pdf_to_png_white_bg(
                pdf_path=pdf,
                out_dir=out_dir,
                dpi=args.dpi,
                poppler_path=poppler_path,
            )
        except Exception as exc:
            print(f"[ERR] {pdf.name}: {exc}")


def new_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Конвертация PDF в PNG с удалением строго белого (#FFFFFF) фона.\n"
            "Белые пиксели становятся полностью прозрачными, без допусков по яркости."
        )
    )
    parser.add_argument(
        "input",
        help="Путь к PDF‑файлу или директории с PDF‑ами",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Папка для сохранения PNG (по умолчанию — рядом с входными файлами)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="DPI для рендеринга PDF (по умолчанию 300)",
    )
    parser.add_argument(
        "--poppler-path",
        help="Путь к бинарникам poppler (если не в PATH; для Windows/нестандартных окружений)",
    )
    return parser


if __name__ == "__main__":
    main()


