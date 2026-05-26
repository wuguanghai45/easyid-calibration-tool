"""Feishu Bitable integration for calibration data sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["run_update"]

if TYPE_CHECKING:
    from feishu.update_camera_offset import run_update


def __getattr__(name: str) -> object:
    if name == "run_update":
        from feishu.update_camera_offset import run_update

        return run_update
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
