"""Configure host NIC for GigE SDK enumeration (multi-homed PCs)."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import struct
import sys
from ctypes import WinDLL, c_char_p, c_int, c_uint, c_uint32
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def ip_to_uint32(ip: str) -> int:
    return struct.unpack("!I", socket.inet_aton(ip))[0]


def resolve_bind_ip(*, device_ip: str | None, interface_name: str | None) -> str | None:
    """Pick the local IPv4 address the GigE SDK should use for discovery."""
    from gvcp_discovery import _iter_host_interfaces, _is_discovery_bind_ip

    host_ifs = [item for item in _iter_host_interfaces() if _is_discovery_bind_ip(item.ip)]
    if not host_ifs:
        return None

    if interface_name:
        needle = interface_name.casefold()
        for host_if in host_ifs:
            if needle in host_if.name.casefold():
                return host_if.ip

    if device_ip:
        try:
            target = ipaddress.IPv4Address(device_ip)
        except ValueError:
            return None
        for host_if in host_ifs:
            for prefix in range(32, 7, -1):
                try:
                    network = ipaddress.IPv4Network(f"{host_if.ip}/{prefix}", strict=False)
                except ValueError:
                    continue
                if target in network:
                    return host_if.ip

    return None


def _try_call_uint32_ip(dll: Any, func_name: str, host_ip: str) -> tuple[bool, str]:
    try:
        func = getattr(dll, func_name)
    except AttributeError:
        return False, f"{func_name}: not exported"
    ip_value = ip_to_uint32(host_ip)
    for argtypes, restype in (
        ((c_uint32,), c_int),
        ((c_uint,), c_int),
        ((c_char_p,), c_int),
    ):
        try:
            func.argtypes = argtypes
            func.restype = restype
            if argtypes[0] is c_char_p:
                ret = int(func(host_ip.encode("ascii")))
            else:
                ret = int(func(ip_value))
            return ret == 0, f"{func_name}: ret={ret}"
        except (TypeError, OSError, ValueError) as exc:
            last = f"{func_name}: {exc}"
    return False, last or f"{func_name}: failed"


def configure_gige_discovery_host(host_ip: str, sdk_root: Path | None = None) -> list[str]:
    """Bind GigE enumeration to a specific host NIC IP (required on multi-homed PCs)."""
    logs: list[str] = [f"gige_host: target={host_ip}"]
    if sys.platform != "win32":
        logs.append("gige_host: skipped (not Windows)")
        return logs

    os.environ["EASYID_GIGE_HOST_IP"] = host_ip

    dll_names = [
        "GigEAPI.dll",
        "MvGigEDev.dll",
        "MvCameraControl.dll",
        "MvGigEVisionSDK.dll",
    ]
    func_names = [
        "MV_GIGE_SetNetExportIp",
        "MV_GIGE_SetEnumNetExportIP",
        "MV_GIGE_SetEnumDeviceNetExportIP",
        "MV_GIGE_SetEnumDevTimeout",
    ]

    search_dirs: list[Path] = []
    if sdk_root is not None:
        search_dirs.extend([sdk_root, sdk_root / "Runtime" / "x64", sdk_root / "Drivers"])
    for name in dll_names:
        loaded = False
        for directory in search_dirs:
            dll_path = directory / name
            if not dll_path.is_file():
                continue
            try:
                dll = WinDLL(str(dll_path))
            except OSError as exc:
                logs.append(f"{name}: load failed ({exc})")
                continue
            for func_name in func_names:
                ok, detail = _try_call_uint32_ip(dll, func_name, host_ip)
                logs.append(f"{name} {detail}")
                if ok:
                    logs.append(f"gige_host: configured via {name}::{func_name}")
                    return logs
            loaded = True
            break
        if not loaded:
            try:
                dll = WinDLL(name)
            except OSError:
                continue
            for func_name in func_names:
                ok, detail = _try_call_uint32_ip(dll, func_name, host_ip)
                logs.append(f"{name} (PATH) {detail}")
                if ok:
                    logs.append(f"gige_host: configured via {name}::{func_name}")
                    return logs

    logs.append("gige_host: no SetNetExport API found (install SDK GigE driver / use SDK sample)")
    return logs


def try_easyid_bind_exports(easyid_dll: Any, host_ip: str) -> list[str]:
    """Probe optional EasyID.dll exports for host bind helpers."""
    logs: list[str] = []
    if sys.platform != "win32":
        return logs
    export_names = [
        "eidSetGigEHostIp",
        "eidSetEnumHostIp",
        "eidSetDiscoveryBindIp",
        "eidSetEnumBindIP",
        "eidGigESetHostIP",
    ]
    for name in export_names:
        try:
            func = getattr(easyid_dll, name)
        except AttributeError:
            continue
        try:
            func.argtypes = (c_char_p,)
            func.restype = c_int
            ret = int(func(host_ip.encode("ascii")))
            logs.append(f"EasyID.{name}: ret={ret}")
            if ret == 0:
                return logs
        except (TypeError, OSError, ValueError) as exc:
            logs.append(f"EasyID.{name}: {exc}")
    return logs
