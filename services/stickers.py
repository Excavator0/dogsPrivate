from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


STICKERS_DIR = Path("templates") / "стикеры"
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _normalize_title(name: str) -> str:
    title = name.replace("_", " ").replace("-", " ").strip()
    if not title:
        return "Стикер"
    # Первая буква заглавная, остальное без изменений для кириллицы
    return title[0].upper() + title[1:]


def list_stickers() -> List[Tuple[str, str]]:
    """
    Возвращает список стикеров для клавиатуры: [(текст, код), ...]
    Рекурсивно сканирует templates/стикеры на предмет изображений.
    Код формируется из относительного пути без расширения, где разделители каталогов заменены на '__'.
    """
    if not STICKERS_DIR.exists():
        return []
    items: List[Tuple[str, str]] = []
    for path in sorted(STICKERS_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        rel = path.relative_to(STICKERS_DIR)
        # Код включает путь без расширения, чтобы избежать коллизий по имени
        code = rel.with_suffix("").as_posix().replace("/", "__").replace(" ", "_")
        text = _normalize_title(path.stem)
        items.append((text, code))
    return items


