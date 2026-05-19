"""Load MVSDK native library with configurable search paths."""

from __future__ import annotations

import os
import platform
import sys
from ctypes import CDLL, WinDLL, get_last_error, windll
from ctypes import wintypes
from pathlib import Path

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


def _register_windows_dll_directory(dll_dir: str) -> None:
    """Add SDK directory to DLL search path so dependent DLLs resolve."""
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(dll_dir)
    else:
        os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")


def _load_windows_mvsdk(path: Path) -> WinDLL:
    """Load MVSDKmd.dll via kernel32.LoadLibraryW and wrap with ctypes WinDLL."""
    abs_path = str(path.resolve())
    _register_windows_dll_directory(str(path.parent.resolve()))

    kernel32 = windll.kernel32
    kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
    kernel32.LoadLibraryW.restype = wintypes.HMODULE

    handle = kernel32.LoadLibraryW(abs_path)
    if not handle:
        err_code = get_last_error()
        raise OSError(err_code, f"LoadLibraryW failed for {abs_path}")

    # WinDLL = stdcall, matching vendor IMVApi.py; handle avoids loading twice.
    return WinDLL(abs_path, handle=handle, use_last_error=True)


def load_mvsdk_library() -> WinDLL | CDLL:
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
                return _load_windows_mvsdk(path)
            return CDLL(str(path.resolve()))
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
