from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from aiogram.types import BufferedInputFile
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
    files = sorted(DESIGNS_DIR.glob("*.pdf"))
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
    data = preview_path.read_bytes()
    return BufferedInputFile(data, filename=f"{design.id}.png")

