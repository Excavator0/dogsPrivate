from pathlib import Path
import io
import argparse
from typing import Iterable

from pdf2image import convert_from_path
from rembg import remove
from PIL import Image


BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "templates" / "одежда"
OUT_DIR = BASE_DIR / "templates" / "одежда_png"
DESIGNS_DIR = BASE_DIR / "templates" / "макеты"


def ensure_output_dir() -> None:
    """
    Создаёт выходную папку, если её нет.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def pdf_to_png_without_background(pdf_path: Path) -> None:
    """
    Конвертирует один PDF-файл в PNG(и) с удалённым фоном.
    Каждый лист PDF сохраняется в отдельный PNG.
    """
    pages = convert_from_path(str(pdf_path), dpi=300)

    for page_index, page in enumerate(pages, start=1):
        # Приводим к RGBA
        page = page.convert("RGBA")

        # Сохраняем страницу во временный буфер PNG
        buf = io.BytesIO()
        page.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Удаляем фон с помощью rembg
        processed_bytes = remove(png_bytes)
        processed_image = Image.open(io.BytesIO(processed_bytes)).convert("RGBA")

        # Формируем имя файла (если страниц несколько — добавляем индекс)
        stem = pdf_path.stem
        if len(pages) > 1:
            stem = f"{stem}_{page_index}"

        out_path = OUT_DIR / f"{stem}.png"
        processed_image.save(out_path)
        print(f"Сохранён файл: {out_path}")


def convert_pdfs_in_place(directory: Path, *, dpi: int = 300, remove_bg: bool = False, delete_pdf: bool = True) -> None:
    """
    Конвертирует все PDF в указанной директории в PNG в той же директории.
    По умолчанию удаляет исходные PDF после успешной конвертации.
    """
    if not directory.exists():
        raise FileNotFoundError(f"Папка не найдена: {directory}")
    pdf_files = sorted(directory.glob("*.pdf"))
    if not pdf_files:
        print(f"В папке {directory} не найдено PDF-файлов.")
        return
    for pdf_path in pdf_files:
        print(f"Обработка файла: {pdf_path}")
        pages = convert_from_path(str(pdf_path), dpi=dpi)
        saved_any = False
        for idx, page in enumerate(pages, start=1):
            page = page.convert("RGBA")
            if remove_bg:
                buf = io.BytesIO()
                page.save(buf, format="PNG")
                page_bytes = buf.getvalue()
                processed_bytes = remove(page_bytes)
                page = Image.open(io.BytesIO(processed_bytes)).convert("RGBA")
            stem = pdf_path.stem if len(pages) == 1 else f"{pdf_path.stem}_{idx}"
            out_path = directory / f"{stem}.png"
            page.save(out_path)
            saved_any = True
            print(f"Сохранён файл: {out_path}")
        if saved_any and delete_pdf:
            try:
                pdf_path.unlink()
                print(f"Удалён PDF: {pdf_path}")
            except OSError as exc:
                print(f"Не удалось удалить {pdf_path}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Конвертация PDF в PNG")
    parser.add_argument("--designs-in-place", action="store_true", help="Конвертировать все PDF из templates/макеты в PNG в той же папке и удалить PDF")
    parser.add_argument("--remove-bg", action="store_true", help="Удалять фон (rembg) при конвертации")
    parser.add_argument("--pdf-dir", type=str, help="Папка с PDF (по умолчанию templates/одежда)")
    parser.add_argument("--out-dir", type=str, help="Папка для PNG (по умолчанию templates/одежда_png)")
    parser.add_argument("--dpi", type=int, default=300, help="DPI для рендеринга PDF")
    args = parser.parse_args()

    if args.designs_in_place:
        convert_pdfs_in_place(DESIGNS_DIR, dpi=args.dpi, remove_bg=args.remove_bg, delete_pdf=True)
        return

    # Режим старого пайплайна (одежда -> png c удалением фона, в другую папку)
    in_dir = Path(args.pdf_dir) if args.pdf_dir else PDF_DIR
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if not in_dir.exists():
        raise FileNotFoundError(f"Папка с PDF не найдена: {in_dir}")
    pdf_files = sorted(in_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"В папке {in_dir} не найдено PDF-файлов.")
        return
    for pdf_file in pdf_files:
        print(f"Обработка файла: {pdf_file}")
        # Сохраняем поведение: удаление фона и сохранение в out_dir
        pages = convert_from_path(str(pdf_file), dpi=args.dpi)
        for page_index, page in enumerate(pages, start=1):
            page = page.convert("RGBA")
            buf = io.BytesIO()
            page.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            processed_bytes = remove(png_bytes) if args.remove_bg or True else png_bytes
            processed_image = Image.open(io.BytesIO(processed_bytes)).convert("RGBA")
            stem = pdf_file.stem if len(pages) == 1 else f"{pdf_file.stem}_{page_index}"
            out_path = out_dir / f"{stem}.png"
            processed_image.save(out_path)
            print(f"Сохранён файл: {out_path}")


if __name__ == "__main__":
    main()


