"""Load MVSDK native library with configurable search paths."""

from __future__ import annotations

import os
import platform
import sys
from ctypes import CDLL, WinDLL, create_unicode_buffer, get_last_error, windll
from ctypes import wintypes
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

LOAD_WITH_ALTERED_SEARCH_PATH = 0x00000008

# PE import table of MVSDKmd.dll (vendor-shipped DLLs only).
MVSDK_VENDOR_DEPENDENCIES = (
    "TinyXmlmd.dll",
    "GCBase_MD_VC120_v3_0.dll",
    "GenApi_MD_VC120_v3_0.dll",
    "CLProtocol_MD_VC120_v3_0.dll",
    "MVlog4cppmd.dll",
    "ImageConvert.dll",
    "ImageSave.dll",
    "CamUpgradeModule.dll",
    "MSVCP120.dll",
    "MSVCR120.dll",
)


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
            "GetLastError=0 (LoadLibrary failed). Usually a dependent DLL is missing "
            "from Runtime/x64. Run: python scripts/check_mvsdk_runtime.py"
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
    length = kernel32.FormatMessageW(0x00001000, None, code, 0, buf, len(buf), None)
    if length:
        return buf.value.strip()
    return f"Windows error {code}"


def _register_windows_dll_directory(dll_dir: str) -> None:
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


def _missing_vendor_dlls(dll_dir: Path) -> list[str]:
    present = {name.lower() for name in _list_runtime_dlls(dll_dir)}
    return [name for name in MVSDK_VENDOR_DEPENDENCIES if name.lower() not in present]


def _preload_runtime_dlls(dll_dir: Path, *, skip_name: str) -> None:
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
    return int(kernel32.LoadLibraryExW(str(path.resolve()), None, LOAD_WITH_ALTERED_SEARCH_PATH))


def _load_library_w(path: Path) -> int:
    kernel32 = windll.kernel32
    kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
    kernel32.LoadLibraryW.restype = wintypes.HMODULE
    return int(kernel32.LoadLibraryW(str(path.resolve())))


def _windows_load_error(path: Path, err_code: int) -> OSError:
    dll_dir = path.parent
    present = _list_runtime_dlls(dll_dir)
    missing = _missing_vendor_dlls(dll_dir)
    py_bits, _ = platform.architecture()
    lines = [
        f"Failed to load {path.name}",
        f"  path: {path.resolve()}",
        f"  Python: {py_bits}",
        f"  win32: {_format_win32_error(err_code)}",
        f"  DLLs in folder ({len(present)}): {', '.join(present) if present else '(none)'}",
    ]
    if missing:
        lines.append(f"  missing vendor DLLs ({len(missing)}):")
        for name in missing:
            lines.append(f"    - {name}")
        lines.append(
            f"  fix: copy the full Runtime/x64 folder from the IMV SDK installer to {dll_dir.resolve()}"
        )
        lines.append("  check: python scripts/check_mvsdk_runtime.py")
    return OSError(err_code, "\n".join(lines))


def _load_windows_mvsdk(path: Path) -> WinDLL:
    dll_dir = path.parent.resolve()
    abs_path = str(path.resolve())

    missing = _missing_vendor_dlls(dll_dir)
    if missing:
        raise _windows_load_error(path, 0)

    _register_windows_dll_directory(str(dll_dir))
    _preload_runtime_dlls(dll_dir, skip_name=path.name)

    handle = _load_library_ex(path)
    if not handle:
        err_code = get_last_error()
        handle = _load_library_w(path)
        if not handle:
            raise _windows_load_error(path, get_last_error() or err_code)

    return WinDLL(abs_path, handle=handle, use_last_error=True)


def load_mvsdk_library() -> WinDLL | CDLL:
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
        "Copy ALL DLLs from the vendor Runtime/x64 folder into project Runtime/x64/. "
        "Run: python scripts/check_mvsdk_runtime.py"
    )
    if last_error is not None:
        raise RuntimeError(f"Failed to load IMV SDK library. {hint}\n{last_error}") from last_error
    raise RuntimeError(f"IMV SDK library not found. {hint}")
