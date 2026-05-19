#!/usr/bin/env python3
"""Diagnose MVSDK Runtime/x64 layout on Windows (run on the target PC)."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

# Vendor DLLs imported by MVSDKmd.dll (from PE import table; system DLLs excluded).
REQUIRED_VENDOR_DLLS = (
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_X64 = PROJECT_ROOT / "Runtime" / "x64"


def main() -> int:
    print(f"Python: {sys.version}")
    print(f"Architecture: {platform.architecture()[0]}")
    print(f"Runtime dir: {RUNTIME_X64}")
    print()

    if not RUNTIME_X64.is_dir():
        print("ERROR: Runtime/x64 directory does not exist.")
        return 1

    present = {p.name.lower(): p for p in RUNTIME_X64.glob("*.dll")}
    print(f"Found {len(present)} DLL(s) in Runtime/x64:")
    for name in sorted(present):
        print(f"  - {name}")
    print()

    missing = [name for name in REQUIRED_VENDOR_DLLS if name.lower() not in present]
    if missing:
        print("MISSING required vendor DLLs (copy from SDK installer Runtime/x64):")
        for name in missing:
            print(f"  - {name}")
        print()
        print("Also install Microsoft Visual C++ 2013 Redistributable (x64) if MSVCP120/MSVCR120 are missing.")
        return 1

    if "mvsdkmd.dll" not in present:
        print("ERROR: MVSDKmd.dll is missing.")
        return 1

    print("All required vendor DLLs are present.")
    if sys.platform != "win32":
        print("(Load test skipped: not on Windows.)")
        return 0

    try:
        from imv_sdk._loader import load_mvsdk_library

        load_mvsdk_library()
        print("OK: MVSDK loaded successfully.")
        return 0
    except Exception as exc:
        print(f"ERROR: load failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
