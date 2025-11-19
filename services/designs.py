from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from aiogram.types import BufferedInputFile
from PIL import Image
from io import BytesIO
from pdf2image import convert_from_path

DESIGNS_DIR = Path("templates") / "макеты"
PREVIEWS_DIR = Path("templates") / "design_previews"
PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
POPPLER_PATH = os.getenv("POPPLER_PATH")
MAX_DESIGNS = 12


@dataclass(frozen=True)
class ReadyDesign:
    id: str
    title: str
    path: Path


def _normalize_title(name: str) -> str:
    cleaned = name.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return "Дизайн"
    return cleaned.title()


def _load_designs() -> List[ReadyDesign]:
    if not DESIGNS_DIR.exists():
        return []
    # Сначала PNG (новый формат), при отсутствии — PDF (старый формат)
    png_files = sorted(DESIGNS_DIR.glob("*.png"))
    pdf_files = sorted(DESIGNS_DIR.glob("*.pdf")) if not png_files else []
    files = png_files or pdf_files
    designs: List[ReadyDesign] = []
    for file in files[:MAX_DESIGNS]:
        designs.append(ReadyDesign(id=file.stem.lower(), title=_normalize_title(file.stem), path=file))
    return designs


READY_DESIGNS: List[ReadyDesign] = _load_designs()


def list_ready_designs() -> List[ReadyDesign]:
    return READY_DESIGNS


def find_design(design_id: str) -> Optional[ReadyDesign]:
    return next((design for design in READY_DESIGNS if design.id == design_id), None)


def _build_preview(design: ReadyDesign) -> Path:
    # Если исходник уже PNG — предпросмотром служит он же
    if design.path.suffix.lower() == ".png":
        return design.path
    target = PREVIEWS_DIR / f"{design.id}.png"
    if target.exists():
        return target
    try:
        pages = convert_from_path(
            str(design.path),
            dpi=200,
            first_page=1,
            last_page=1,
            poppler_path=POPPLER_PATH,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Не удалось подготовить предпросмотр {design.path.name}: {exc}") from exc
    if not pages:
        raise RuntimeError(f"PDF {design.path} пустой")
    page = pages[0].convert("RGB")
    page.save(target)
    return target


def get_design_preview(design: ReadyDesign) -> BufferedInputFile:
    preview_path = _build_preview(design)
    # Открываем изображение и делаем лёгкий превью-даунскейл + JPEG
    img = Image.open(preview_path)
    max_side = 1600
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    bio = BytesIO()
    img.save(bio, "JPEG", quality=85, optimize=True)
    bio.seek(0)
    return BufferedInputFile(bio.getvalue(), filename=f"{design.id}.jpg")

