from __future__ import annotations

from pathlib import Path
from functools import lru_cache
from typing import List, Tuple, Optional, Dict


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
        code = _build_sticker_code(rel)
        text = _normalize_title(path.stem)
        items.append((text, code))
    return items


def _build_sticker_code(rel: Path) -> str:
    """
    Строит код стикера из относительного пути:
    - убираем расширение
    - разделители каталогов → '__'
    - пробелы → '_'
    """
    return rel.with_suffix("").as_posix().replace("/", "__").replace(" ", "_")


def _build_category_code(folder_name: str) -> str:
    """
    Код категории строим из имени папки:
    - пробелы → '_'
    """
    return folder_name.replace(" ", "_")


@lru_cache(maxsize=1)
def _scan_stickers() -> Dict[str, Path]:
    """
    Сканырует все изображения и возвращает mapping {sticker_code: path}.
    Используется для быстрого поиска пути по коду.
    """
    mapping: Dict[str, Path] = {}
    if not STICKERS_DIR.exists():
        return mapping
    for path in STICKERS_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        rel = path.relative_to(STICKERS_DIR)
        code = _build_sticker_code(rel)
        mapping[code] = path
    return mapping


def get_sticker_path(code: str) -> Optional[Path]:
    """
    Возвращает путь к файлу стикера по его коду (как в БД/состоянии).
    """
    return _scan_stickers().get(code)


def list_sticker_categories() -> List[Tuple[str, str]]:
    """
    Список категорий стикеров на основе подпапок в templates/стикеры.
    Возвращает [(название, код), ...].
    """
    if not STICKERS_DIR.exists():
        return []

    categories: Dict[str, str] = {}
    for path in STICKERS_DIR.iterdir():
        if not path.is_dir():
            continue
        code = _build_category_code(path.name)
        title = _normalize_title(path.name)
        categories[code] = title

    # Сортируем по заголовку для стабильного порядка
    return sorted(((title, code) for code, title in categories.items()), key=lambda x: x[0])


def list_stickers_in_category(category_code: str) -> List[Tuple[str, str]]:
    """
    Возвращает список стикеров внутри указанной категории (подпапки).
    category_code строится из имени папки (пробелы → '_').
    """
    if not STICKERS_DIR.exists():
        return []

    # Находим реальную папку по коду категории
    target_dir: Optional[Path] = None
    for path in STICKERS_DIR.iterdir():
        if not path.is_dir():
            continue
        if _build_category_code(path.name) == category_code:
            target_dir = path
            break

    if not target_dir or not target_dir.exists():
        return []

    items: List[Tuple[str, str]] = []
    for path in sorted(target_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        rel = path.relative_to(STICKERS_DIR)
        code = _build_sticker_code(rel)
        text = _normalize_title(path.stem)
        items.append((text, code))

    return items


