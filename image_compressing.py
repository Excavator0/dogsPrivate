from pathlib import Path
from io import BytesIO

from PIL import Image

# Максимальный размер файла в байтах (2 МБ)
MAX_SIZE_BYTES = 2 * 1024 * 1024

BASE_DIR = Path(__file__).resolve().parent
PNG_DIR = BASE_DIR / "templates" / "new clothes"
# Папка для сжатых изображений (оригиналы не трогаем)
OUT_DIR = BASE_DIR / "templates" / "new clothes compressed"

# Минимальное допустимое разрешение (чтоб не ужать до абсурда)
MIN_WIDTH = 1200
MIN_HEIGHT = 1200


def compress_png_to_target_size(path: Path, out_dir: Path, max_bytes: int = MAX_SIZE_BYTES) -> None:
    """
    Сжимает PNG-файл (уменьшением разрешения) так, чтобы размер стал <= max_bytes.
    Перезаписывает исходный файл.
    """
    if not path.is_file() or path.suffix.lower() != ".png":
        return

    print(f"Обработка: {path.name}")

    img = Image.open(path)
    img = img.convert("RGBA")  # на всякий случай

    # Исходные размеры
    width, height = img.size

    # Путь для сохранения (в другую папку, с тем же именем)
    out_path = out_dir / path.name

    # Пробуем текущий размер без изменения
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()

    if len(data) <= max_bytes:
        # Просто сохраняем оптимизированный вариант в новую папку
        with out_path.open("wb") as f:
            f.write(data)
        print(f"  Уже <= 2 МБ ({len(data) / 1024:.1f} КБ), сохранено без изменения разрешения.")
        return

    # Циклически уменьшаем разрешение, пока не уложимся в лимит
    current_img = img
    attempt = 0

    while True:
        attempt += 1

        # Сохраняем в память и проверяем размер
        buf = BytesIO()
        current_img.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        size = len(data)

        print(f"  Попытка {attempt}: {current_img.size}, {size / 1024:.1f} КБ")

        if size <= max_bytes:
            # Уложились — записываем в выходную папку
            with out_path.open("wb") as f:
                f.write(data)
            print(f"  Успех: {path.name} -> {size / 1024:.1f} КБ")
            break

        # Если уже слишком маленькое изображение — останавливаемся
        w, h = current_img.size
        if w <= MIN_WIDTH or h <= MIN_HEIGHT:
            print("  Достигнут минимальный размер, дальше ужимать нельзя без сильной потери качества.")
            # Всё равно перезапишем последней версией (на всякий случай) в выходную папку
            with out_path.open("wb") as f:
                f.write(data)
            break

        # Оцениваем коэффициент уменьшения:
        # теоретически размер ~ пропорционален площади (w*h),
        # значит масштаб ≈ sqrt(нужный_размер / текущий_размер)
        scale = (max_bytes / size) ** 0.5

        # Добавим небольшой запас, чтобы не делать слишком много попыток
        scale *= 0.95

        # Но не уменьшаем слишком резко (не более чем на 50% за шаг)
        scale = max(scale, 0.5)

        new_w = int(w * scale)
        new_h = int(h * scale)

        # Гарантия, что не вылезем ниже минимального размера
        if new_w < MIN_WIDTH and w > MIN_WIDTH:
            new_w = MIN_WIDTH
        if new_h < MIN_HEIGHT and h > MIN_HEIGHT:
            new_h = MIN_HEIGHT

        # Масштабируем
        current_img = current_img.resize((new_w, new_h), Image.LANCZOS)


def main():
    if not PNG_DIR.exists():
        print(f"Папка не найдена: {PNG_DIR}")
        return

    # Создаём выходную папку, если её нет
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    png_files = sorted(PNG_DIR.glob("*.png"))
    if not png_files:
        print(f"В папке {PNG_DIR} нет PNG-файлов.")
        return

    for png_path in png_files:
        compress_png_to_target_size(png_path, OUT_DIR, MAX_SIZE_BYTES)


if __name__ == "__main__":
    main()