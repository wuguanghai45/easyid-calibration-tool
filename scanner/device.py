"""IMV device enumeration and connection."""

from __future__ import annotations

import ipaddress
import logging
import socket
from ctypes import byref, c_void_p
from typing import TYPE_CHECKING, Any

from imv_sdk.IMVDefines import (
    IMV_DeviceInfo,
    IMV_DeviceList,
    IMV_ECreateHandleMode,
    IMV_EInterfaceType,
    IMV_INVALID_IP,
    IMV_OK,
    typeGigeCamera,
    typeU3vCamera,
)

from scanner_utils import ScannerProtocolError

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)

# GigE Vision control protocol port (used only to discover routed local IPv4).
_GIGE_CONTROL_PORT = 3956


def _mv_camera():
    from imv_sdk.IMVApi import MvCamera

    return MvCamera

_CAMERA_TYPE_NAMES = {
    typeGigeCamera: "GigE",
    typeU3vCamera: "U3V",
}


def _decode(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00")
    return str(value).strip("\x00")


def _device_info_to_dict(info: IMV_DeviceInfo, index: int) -> dict[str, Any]:
    camera_type = int(info.nCameraType)
    ip_address = ""
    mac_address = ""
    if camera_type == typeGigeCamera:
        gige = info.DeviceSpecificInfo.gigeDeviceInfo
        ip_address = _decode(gige.ipAddress)
        mac_address = _decode(gige.macAddress)

    return {
        "index": index,
        "camera_type": _CAMERA_TYPE_NAMES.get(camera_type, f"unknown({camera_type})"),
        "vendor_name": _decode(info.vendorName),
        "model_name": _decode(info.modelName),
        "serial_number": _decode(info.serialNumber),
        "ip_address": ip_address,
        "mac_address": mac_address,
        "interface_name": _decode(info.interfaceName),
        "camera_key": _decode(info.cameraKey),
        "device_version": _decode(info.deviceVersion),
    }


def enum_devices(*, unicast_ip: str | None = None) -> list[dict[str, Any]]:
    MvCamera = _mv_camera()
    device_list = IMV_DeviceList()
    if unicast_ip:
        ret = MvCamera.IMV_EnumDevicesByUnicast(device_list, unicast_ip)
    else:
        ret = MvCamera.IMV_EnumDevices(device_list, IMV_EInterfaceType.interfaceTypeAll)
    if ret != IMV_OK:
        raise ScannerProtocolError(f"IMV_EnumDevices failed with error code {ret}")

    devices: list[dict[str, Any]] = []
    for index in range(int(device_list.nDevNum)):
        info = device_list.pDevInfo[index]
        devices.append(_device_info_to_dict(info, index))
    logger.info("Discovered %d device(s) via IMV SDK.", len(devices))
    return devices


def _collect_local_ipv4() -> list[str]:
    host_name = socket.gethostname()
    addresses: set[str] = set()
    try:
        for result in socket.getaddrinfo(host_name, None, socket.AF_INET, socket.SOCK_DGRAM):
            ip = result[4][0]
            if ip and ip != "127.0.0.1":
                addresses.add(ip)
    except OSError:
        pass
    return sorted(addresses)


def _local_ipv4_for_peer(peer_ip: str) -> str | None:
    """Return the local IPv4 the OS would use to reach peer_ip (works on Windows multi-NIC)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect((peer_ip, _GIGE_CONTROL_PORT))
            local_ip = sock.getsockname()[0]
    except OSError:
        return None
    if local_ip and local_ip != "127.0.0.1":
        return local_ip
    return None


def _device_subnet(device_ip: str) -> ipaddress.IPv4Network | None:
    try:
        return ipaddress.ip_network(f"{device_ip}/24", strict=False)
    except ValueError:
        return None


def find_local_ip_for_device(device_ip: str) -> str | None:
    """Find a host IPv4 on the same /24 subnet as the GigE device."""
    device_net = _device_subnet(device_ip)
    if device_net is None:
        return None

    routed = _local_ipv4_for_peer(device_ip)
    if routed:
        try:
            if ipaddress.ip_address(routed) in device_net:
                return routed
        except ValueError:
            pass

    for local_ip in _collect_local_ipv4():
        try:
            if ipaddress.ip_address(local_ip) in device_net:
                return local_ip
        except ValueError:
            continue
    return None


def assert_gige_host_subnet(device: dict[str, Any], device_ip: str | None = None) -> str:
    """
    Ensure the host has an IPv4 on the device subnet (required for IMV_Open on GigE).

    Returns the local bind IP to use for unicast enumeration.
    """
    if device.get("camera_type") != "GigE":
        return ""
    ip = (device_ip or str(device.get("ip_address", ""))).strip()
    if not ip:
        return ""

    bind_ip = find_local_ip_for_device(ip)
    if bind_ip:
        return bind_ip

    prefix = ".".join(ip.split(".")[:3])
    local_ips = _collect_local_ipv4()
    routed = _local_ipv4_for_peer(ip)
    hint = (
        f"Device is at {ip} but the host is not on the same subnet (SDK error -107 / IMV_INVALID_IP). "
        f"Add a static IPv4 on the camera NIC, e.g. {prefix}.10 with mask 255.255.255.0, then retry."
    )
    details = [f"host_ipv4={', '.join(local_ips) or '(none)'}"]
    if routed:
        details.append(f"routed_local={routed}")
    raise ScannerProtocolError(f"{hint} ({'; '.join(details)})")


def refresh_device_via_unicast(
    device: dict[str, Any],
    *,
    serial_number: str | None = None,
    ip: str | None = None,
    interface_name: str | None = None,
) -> dict[str, Any]:
    """Re-enumerate on the NIC that can reach the device and return the updated entry."""
    device_ip = str(device.get("ip_address", ""))
    bind_ip = _resolve_unicast_ip(interface_name, device_ip) or find_local_ip_for_device(device_ip)
    if not bind_ip:
        assert_gige_host_subnet(device, device_ip)
        bind_ip = find_local_ip_for_device(device_ip) or ""

    logger.info("Using host %s to reach device %s", bind_ip, device_ip or "unknown")
    devices = enum_devices(unicast_ip=bind_ip)
    return find_device(
        devices,
        serial_number=serial_number or str(device.get("serial_number", "")) or None,
        ip=ip or device_ip or None,
        interface_name=interface_name,
    )


def _resolve_unicast_ip(interface_hint: str | None, device_ip: str) -> str | None:
    if not interface_hint:
        return find_local_ip_for_device(device_ip) if device_ip else None
    needle = interface_hint.casefold()
    for local_ip in _collect_local_ipv4():
        if needle in local_ip.casefold():
            return local_ip
    routed = _local_ipv4_for_peer(device_ip) if device_ip else None
    if routed and needle in routed.casefold():
        return routed
    for local_ip in _collect_local_ipv4():
        try:
            if ipaddress.ip_address(local_ip) in ipaddress.ip_network(f"{device_ip}/24", strict=False):
                return local_ip
        except ValueError:
            continue
    return None


def _filter_by_interface(devices: list[dict[str, Any]], interface_name: str | None) -> list[dict[str, Any]]:
    if not interface_name:
        return devices
    needle = interface_name.casefold()
    filtered = [dev for dev in devices if needle in str(dev.get("interface_name", "")).casefold()]
    if filtered:
        return filtered
    # Fallback: match device IP subnet against local NIC addresses.
    local_ips = _collect_local_ipv4()
    result: list[dict[str, Any]] = []
    for dev in devices:
        device_ip = str(dev.get("ip_address", ""))
        if not device_ip:
            continue
        for local_ip in local_ips:
            if needle in local_ip.casefold():
                try:
                    if ipaddress.ip_address(local_ip) in ipaddress.ip_network(f"{device_ip}/24", strict=False):
                        result.append(dev)
                        break
                except ValueError:
                    continue
    return result or devices


def find_device(
    devices: list[dict[str, Any]],
    *,
    serial_number: str | None = None,
    ip: str | None = None,
    interface_name: str | None = None,
) -> dict[str, Any]:
    target = serial_number or ip
    if not target:
        raise ValueError("Either serial_number or ip is required.")

    scoped = _filter_by_interface(devices, interface_name)
    if not scoped:
        raise ScannerProtocolError("No scanner device found (IMV enumeration).")

    matched = [
        dev
        for dev in scoped
        if (serial_number and dev.get("serial_number") == serial_number)
        or (ip and dev.get("ip_address") == ip)
    ]
    if not matched:
        raise ScannerProtocolError(f"Device not found for target={target}")

    if len(matched) > 1 and not interface_name:
        interfaces = ", ".join(sorted({str(dev.get("interface_name") or "unknown") for dev in matched}))
        raise ScannerProtocolError(
            f"Multiple devices matched target {target} on interfaces [{interfaces}]. "
            "Please specify --interface or run --list-devices."
        )
    return matched[0]


def open_camera(
    device: dict[str, Any],
    *,
    serial_number: str | None = None,
    ip: str | None = None,
    interface_name: str | None = None,
) -> tuple["MvCamera", dict[str, Any]]:
    MvCamera = _mv_camera()
    cam = MvCamera()
    device_ip = str(device.get("ip_address", ""))
    if device.get("camera_type") == "GigE" and device_ip:
        assert_gige_host_subnet(device, device_ip)
    unicast_ip = _resolve_unicast_ip(interface_name, device_ip)

    if ip and device_ip == ip:
        ret = cam.IMV_CreateHandle(IMV_ECreateHandleMode.modeByIPAddress, ip.encode("utf-8"))
        if ret != IMV_OK:
            index = int(device["index"])
            ret = cam.IMV_CreateHandle(IMV_ECreateHandleMode.modeByIndex, byref(c_void_p(index)))
    else:
        index = int(device["index"])
        ret = cam.IMV_CreateHandle(IMV_ECreateHandleMode.modeByIndex, byref(c_void_p(index)))

    if ret != IMV_OK:
        raise ScannerProtocolError(f"IMV_CreateHandle failed with error code {ret}")

    ret = cam.IMV_Open()
    if ret != IMV_OK:
        cam.IMV_DestroyHandle()
        if ret == IMV_INVALID_IP and device.get("camera_type") == "GigE":
            assert_gige_host_subnet(device, device_ip)
        raise ScannerProtocolError(f"IMV_Open failed with error code {ret}")

    sdk_info = IMV_DeviceInfo()
    ret = cam.IMV_GetDeviceInfo(sdk_info)
    if ret == IMV_OK:
        device_info = _device_info_to_dict(sdk_info, int(device.get("index", 0)))
    else:
        device_info = dict(device)

    device_info["sdk_version"] = _decode(MvCamera.IMV_GetVersion() or b"")
    if unicast_ip:
        device_info["bind_ip"] = unicast_ip
    if interface_name:
        device_info["interface_filter"] = interface_name
    return cam, device_info


def close_camera(cam: "MvCamera | None") -> None:
    if cam is None:
        return
    if cam.IMV_IsOpen():
        if cam.IMV_IsGrabbing():
            cam.IMV_StopGrabbing()
        cam.IMV_Close()
    if cam.handle:
        cam.IMV_DestroyHandle()
