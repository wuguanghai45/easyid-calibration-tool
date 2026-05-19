"""Load MVSDK native library with configurable search paths."""

from __future__ import annotations

import os
import platform
import sys
from ctypes import CDLL
from pathlib import Path

if sys.platform == "win32":
    from ctypes import WinDLL
else:
    WinDLL = None  # type: ignore[misc, assignment]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _candidate_paths() -> list[Path]:
    env_path = os.environ.get("IMV_SDK_LIB", "").strip()
    if env_path:
        yield Path(env_path)

    if sys.platform == "win32":
        bits, _ = platform.architecture()
        if bits == "64bit":
            yield _PROJECT_ROOT / "Runtime" / "x64" / "MVSDKmd.dll"
        else:
            yield _PROJECT_ROOT / "Runtime" / "Win32" / "MVSDKmd.dll"
        yield _PROJECT_ROOT / "SDKPython" / "Runtime" / "x64" / "MVSDKmd.dll"
    elif sys.platform.startswith("linux"):
        yield _PROJECT_ROOT / "lib" / "libMVSDK.so"
        yield _PROJECT_ROOT / "SDKPython" / "lib" / "libMVSDK.so"


def load_mvsdk_library():
    """Return loaded MVSDK DLL/so or raise RuntimeError with setup hints."""
    if sys.platform == "darwin":
        raise RuntimeError(
            "IMV MVSDK is not supported on macOS. Run on Windows or Linux with MVSDK installed. "
            "See SDKPython/sdk.pdf for native library setup."
        )

    last_error: Exception | None = None
    for path in _candidate_paths():
        if not path.is_file():
            continue
        try:
            if sys.platform == "win32":
                return WinDLL(str(path))
            return CDLL(str(path))
        except OSError as exc:
            last_error = exc

    hint = (
        "Set IMV_SDK_LIB to the full path of MVSDKmd.dll (Windows) or libMVSDK.so (Linux), "
        "or place the library under Runtime/x64/ or lib/ in the project root. "
        "See SDKPython/sdk.pdf."
    )
    if last_error is not None:
        raise RuntimeError(f"Failed to load IMV SDK library. {hint}") from last_error
    raise RuntimeError(f"IMV SDK library not found. {hint}")
