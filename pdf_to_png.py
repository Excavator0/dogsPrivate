from pathlib import Path
import io

from pdf2image import convert_from_path
from rembg import remove
from PIL import Image


BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "templates" / "одежда"
OUT_DIR = BASE_DIR / "templates" / "одежда_png"


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


def main() -> None:
    ensure_output_dir()

    if not PDF_DIR.exists():
        raise FileNotFoundError(f"Папка с PDF не найдена: {PDF_DIR}")

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"В папке {PDF_DIR} не найдено PDF-файлов.")
        return

    for pdf_file in pdf_files:
        print(f"Обработка файла: {pdf_file}")
        pdf_to_png_without_background(pdf_file)


if __name__ == "__main__":
    main()


