"""Generic utilities for scanner calibration workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None


class ScannerProtocolError(RuntimeError):
    """Raised when IMV SDK operations fail."""


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


def save_frame_image(
    base_path: Path,
    image_bytes: bytes,
    *,
    is_jpeg: bool,
    width: int = 0,
    height: int = 0,
) -> Path:
    if not image_bytes:
        raw_path = base_path.with_suffix(".bin")
        raw_path.write_bytes(image_bytes)
        return raw_path

    if is_jpeg:
        jpg_path = base_path.with_suffix(".jpg")
        jpg_path.write_bytes(image_bytes)
        return jpg_path

    if Image is not None and width > 0 and height > 0:
        try:
            png_path = base_path.with_suffix(".png")
            image = Image.frombytes("L", (width, height), image_bytes)
            image.save(png_path)
            return png_path
        except Exception:
            pass

    raw_path = base_path.with_suffix(".raw")
    raw_path.write_bytes(image_bytes)
    return raw_path
