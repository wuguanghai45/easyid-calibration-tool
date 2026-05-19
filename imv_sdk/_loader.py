"""Load MVSDK native library with configurable search paths."""

from __future__ import annotations

import os
import platform
import sys
from ctypes import CDLL, WinDLL, create_unicode_buffer, get_last_error, windll
from ctypes import wintypes
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# LoadLibraryEx flags: search for dependents in the DLL's directory first.
LOAD_WITH_ALTERED_SEARCH_PATH = 0x00000008


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


def _format_win32_error(code: int) -> str:
    if code == 0:
        return (
            "GetLastError=0 (LoadLibrary failed). This usually means a dependent DLL "
            "is missing from the same folder as MVSDKmd.dll."
        )
    kernel32 = windll.kernel32
    kernel32.FormatMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    kernel32.FormatMessageW.restype = wintypes.DWORD
    buf = create_unicode_buffer(512)
    flags = 0x00001000  # FORMAT_MESSAGE_FROM_SYSTEM
    length = kernel32.FormatMessageW(flags, None, code, 0, buf, len(buf), None)
    if length:
        return buf.value.strip()
    return f"Windows error {code}"


def _register_windows_dll_directory(dll_dir: str) -> None:
    """Add SDK directory to DLL search path so dependent DLLs resolve."""
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(dll_dir)
    kernel32 = windll.kernel32
    if hasattr(kernel32, "SetDllDirectoryW"):
        kernel32.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
        kernel32.SetDllDirectoryW.restype = wintypes.BOOL
        kernel32.SetDllDirectoryW(dll_dir)
    os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")


def _list_runtime_dlls(dll_dir: Path) -> list[str]:
    if not dll_dir.is_dir():
        return []
    return sorted(item.name for item in dll_dir.glob("*.dll"))


def _preload_runtime_dlls(dll_dir: Path, *, skip_name: str) -> None:
    """Pre-load peer DLLs in the SDK directory (dependencies for MVSDKmd.dll)."""
    kernel32 = windll.kernel32
    kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
    kernel32.LoadLibraryW.restype = wintypes.HMODULE
    for dll_path in sorted(dll_dir.glob("*.dll")):
        if dll_path.name.lower() == skip_name.lower():
            continue
        kernel32.LoadLibraryW(str(dll_path.resolve()))


def _load_library_ex(path: Path) -> int:
    kernel32 = windll.kernel32
    kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel32.LoadLibraryExW.restype = wintypes.HMODULE
    abs_path = str(path.resolve())
    return int(kernel32.LoadLibraryExW(abs_path, None, LOAD_WITH_ALTERED_SEARCH_PATH))


def _load_library_w(path: Path) -> int:
    kernel32 = windll.kernel32
    kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
    kernel32.LoadLibraryW.restype = wintypes.HMODULE
    return int(kernel32.LoadLibraryW(str(path.resolve())))


def _windows_load_error(path: Path, err_code: int) -> OSError:
    dll_dir = path.parent
    present = _list_runtime_dlls(dll_dir)
    py_bits, _ = platform.architecture()
    msg = (
        f"Failed to load {path.name}\n"
        f"  path: {path.resolve()}\n"
        f"  Python: {py_bits}\n"
        f"  win32: {_format_win32_error(err_code)}\n"
        f"  DLLs in folder ({len(present)}): {', '.join(present) if present else '(none)'}\n"
    )
    if len(present) <= 1:
        msg += (
            "  hint: MVSDKmd.dll requires other DLLs from the vendor package. "
            "Copy the entire Runtime/x64 directory from the SDK installer into "
            f"{dll_dir.resolve()}"
        )
    return OSError(err_code, msg)


def _load_windows_mvsdk(path: Path) -> WinDLL:
    """Load MVSDKmd.dll via LoadLibraryExW / LoadLibraryW and wrap with ctypes WinDLL."""
    dll_dir = path.parent.resolve()
    abs_path = str(path.resolve())
    _register_windows_dll_directory(str(dll_dir))
    _preload_runtime_dlls(dll_dir, skip_name=path.name)

    handle = _load_library_ex(path)
    if not handle:
        err_code = get_last_error()
        handle = _load_library_w(path)
        if not handle:
            err_code = get_last_error() or err_code
            raise _windows_load_error(path, err_code)

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
        "On Windows, copy ALL DLLs from the vendor Runtime/x64 folder, not only MVSDKmd.dll. "
        "See SDKPython/sdk.pdf."
    )
    if last_error is not None:
        raise RuntimeError(f"Failed to load IMV SDK library. {hint}\n{last_error}") from last_error
    raise RuntimeError(f"IMV SDK library not found. {hint}")
