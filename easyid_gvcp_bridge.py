"""Bridge GVCP discovery results into EasyID SDK device structures."""

from __future__ import annotations

from ctypes import POINTER, byref, c_int, c_void_p
from typing import Any

import EasyID


def _write_cstr(buffer: Any, value: str) -> None:
    raw = (value or "").encode("ascii", errors="ignore")
    size = len(buffer)
    for index in range(size):
        buffer[index] = 0
    for index, byte in enumerate(raw):
        if index >= size:
            break
        buffer[index] = byte


def fill_eid_device_info_from_gvcp(info: EasyID.EidDeviceInfo, gvcp: dict[str, Any]) -> None:
    info.deviceType = int(gvcp.get("device_type", EasyID.EidDeviceType.eidDeviceTypeGige))
    info.interfaceType = int(gvcp.get("interface_type", EasyID.EidInterfaceType.eidInterfaceTypeGige))
    _write_cstr(info.deviceID, gvcp.get("device_id", ""))
    _write_cstr(info.cameraName, gvcp.get("camera_name", ""))
    _write_cstr(info.serialNumber, gvcp.get("serial_number", ""))
    _write_cstr(info.vendorName, gvcp.get("vendor_name", ""))
    _write_cstr(info.modelName, gvcp.get("model_name", ""))
    _write_cstr(info.manufactureInfo, gvcp.get("manufacture_info", ""))
    _write_cstr(info.deviceVersion, gvcp.get("device_version", ""))
    _write_cstr(info.interfaceName, gvcp.get("interface_name", ""))

    gige = info.gigeDeviceInfo
    _write_cstr(gige.ipAddress, gvcp.get("ip_address", ""))
    _write_cstr(gige.subnetMask, gvcp.get("subnet_mask", ""))
    _write_cstr(gige.defaultGateWay, gvcp.get("gateway", ""))
    _write_cstr(gige.macAddress, gvcp.get("mac_address", ""))
    gige.isIpValid = bool(gvcp.get("ip_address"))


def try_create_device_from_gvcp_info(camera: EasyID.Camera, gvcp: dict[str, Any]) -> int:
    """Try SDK entry points that accept a populated EidDeviceInfo (if exported)."""
    info = EasyID.EidDeviceInfo()
    fill_eid_device_info_from_gvcp(info, gvcp)
    easyid = EasyID.EASYID

    export_names = (
        "eidCreateDeviceByInfo",
        "eidCreateDeviceEx",
        "eidCreateDeviceInfo",
    )
    for name in export_names:
        try:
            fn = getattr(easyid, name)
        except AttributeError:
            continue
        for argtypes, call in (
            (
                (POINTER(EasyID.EidDeviceInfo), POINTER(c_void_p)),
                lambda: _call_info_out_handle(fn, info, camera),
            ),
            (
                (POINTER(EasyID.EidDeviceInfo),),
                lambda: _call_info_only(fn, info, camera),
            ),
            (
                (POINTER(c_void_p), POINTER(EasyID.EidDeviceInfo)),
                lambda: _call_handle_info(fn, info, camera),
            ),
        ):
            try:
                fn.argtypes = argtypes
                fn.restype = c_int
                ret = int(call())
                if ret == EasyID.EidError.eidErrorOK and camera.handle:
                    return EasyID.EidError.eidErrorOK
            except (TypeError, OSError, ValueError):
                continue
    return EasyID.EidError.eidErrorInvalidParameter


def _call_info_out_handle(fn: Any, info: EasyID.EidDeviceInfo, camera: EasyID.Camera) -> int:
    camera.handle = c_void_p()
    out = c_void_p()
    ret = int(fn(byref(info), byref(out)))
    if ret == EasyID.EidError.eidErrorOK and out.value:
        camera.handle = out
    return ret


def _call_info_only(fn: Any, info: EasyID.EidDeviceInfo, camera: EasyID.Camera) -> int:
    camera.handle = c_void_p()
    fn.restype = POINTER(c_void_p)
    result = fn(byref(info))
    if result:
        camera.handle = result
        return EasyID.EidError.eidErrorOK
    return EasyID.EidError.eidErrorInvalidParameter


def _call_handle_info(fn: Any, info: EasyID.EidDeviceInfo, camera: EasyID.Camera) -> int:
    camera.handle = c_void_p()
    out = c_void_p()
    ret = int(fn(byref(out), byref(info)))
    if ret == EasyID.EidError.eidErrorOK and out.value:
        camera.handle = out
    return ret
