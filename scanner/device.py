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
    IMV_ECameraAccessPermission,
    IMV_ECreateHandleMode,
    IMV_EInterfaceType,
    IMV_ERROR,
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


def _normalize_device_identifier(value: Any) -> str:
    """Normalize an SDK hardware identifier for stable duplicate detection."""
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _physical_device_key(device: dict[str, Any]) -> tuple[str, str] | None:
    """Return the strongest available identity key for one physical scanner."""
    mac_address = _normalize_device_identifier(device.get("mac_address", ""))
    if mac_address:
        return ("mac", mac_address)

    serial_number = _normalize_device_identifier(device.get("serial_number", ""))
    if serial_number:
        return ("serial", serial_number)

    camera_key = _normalize_device_identifier(device.get("camera_key", ""))
    if camera_key:
        return ("camera_key", camera_key)
    return None


def _deduplicate_physical_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated SDK entries while preserving distinct physical scanners.

    IMV can retain an entry for a recently closed handle and return it together
    with the newly discovered entry. The later entry is retained because it has
    the current enumeration index and network information. Devices without a
    stable MAC, serial number or camera key are never collapsed.
    """
    deduplicated: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], int] = {}

    for device in devices:
        identity = _physical_device_key(device)
        if identity is None or identity not in positions:
            if identity is not None:
                positions[identity] = len(deduplicated)
            deduplicated.append(device)
            continue

        position = positions[identity]
        previous = deduplicated[position]
        deduplicated[position] = device
        logger.warning(
            "Collapsed duplicate IMV device entry by %s (old index=%s, new index=%s, SN=%s, MAC=%s)",
            identity[0],
            previous.get("index"),
            device.get("index"),
            device.get("serial_number") or previous.get("serial_number") or "n/a",
            device.get("mac_address") or previous.get("mac_address") or "n/a",
        )

    return deduplicated


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
    unique_devices = _deduplicate_physical_devices(devices)
    logger.info(
        "Discovered %d physical device(s) from %d IMV SDK entry/entries.",
        len(unique_devices),
        len(devices),
    )
    return unique_devices


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


def select_camera_host_ip() -> str | None:
    """Pick the most likely NIC IPv4 for the industrial camera (not VPN/WAN)."""
    candidates = _collect_local_ipv4()
    if not candidates:
        return None

    def score(ip: str) -> tuple[int, str]:
        if ip.startswith("192.168."):
            return (300, ip)
        if ip.startswith("172."):
            return (200, ip)
        if ip.startswith("10."):
            return (50, ip)
        return (100, ip)

    return max(candidates, key=score)


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
    sn = serial_number or str(device.get("serial_number", "")) or None
    lookup_ip = ip or device_ip or None

    bind_ip = _resolve_unicast_ip(interface_name, device_ip) or find_local_ip_for_device(device_ip)
    if not bind_ip:
        assert_gige_host_subnet(device, device_ip)
        bind_ip = find_local_ip_for_device(device_ip) or ""

    def _lookup(devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not devices:
            return None
        try:
            return find_device(
                devices,
                serial_number=sn,
                ip=lookup_ip,
                interface_name=interface_name,
            )
        except ScannerProtocolError:
            return None

    logger.info("Using host %s to reach device %s", bind_ip, device_ip or "unknown")
    refreshed = _lookup(enum_devices(unicast_ip=bind_ip))
    if refreshed is not None:
        return refreshed

    logger.info(
        "Unicast enumeration on %s returned no devices; falling back to global IMV_EnumDevices",
        bind_ip,
    )
    refreshed = _lookup(enum_devices())
    if refreshed is not None:
        return refreshed

    if find_local_ip_for_device(device_ip):
        logger.info(
            "Using device entry from initial scan (index=%s, ip=%s)",
            device.get("index"),
            device_ip,
        )
        return device

    raise ScannerProtocolError(
        f"Device not found after enumeration (target SN={sn or 'n/a'}, ip={lookup_ip or 'n/a'})."
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


def imv_error_hint(code: int) -> str:
    """Human-readable hint for common IMV SDK return codes."""
    hints = {
        IMV_ERROR: (
            "generic SDK error (often: device busy, wrong NIC, or stale enumeration index). "
            "Close MVS/other camera apps, verify PC IP is on the same subnet as the device, "
            "wait a few seconds and retry."
        ),
        IMV_INVALID_IP: "host IP subnet does not match the GigE device",
        -106: "camera resource invalid (device may be in use)",
        -111: "property access denied",
    }
    extra = hints.get(code, "")
    return f"error code {code}" + (f" — {extra}" if extra else "")


def _destroy_handle(cam: "MvCamera") -> None:
    if cam.handle:
        cam.IMV_DestroyHandle()


def _create_handle(cam: "MvCamera", mode: int, param: bytes | int) -> int:
    if mode == IMV_ECreateHandleMode.modeByIndex:
        return cam.IMV_CreateHandle(mode, byref(c_void_p(int(param))))
    return cam.IMV_CreateHandle(mode, param)


def _open_camera_handle(cam: "MvCamera") -> int:
    ret = cam.IMV_Open()
    if ret == IMV_OK:
        return ret
    ret2 = cam.IMV_OpenEx(IMV_ECameraAccessPermission.accessPermissionControl)
    if ret2 == IMV_OK:
        return ret2
    return cam.IMV_OpenEx(IMV_ECameraAccessPermission.accessPermissionExclusive)


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
    connect_ip = (ip or device_ip).strip()
    if device.get("camera_type") == "GigE" and device_ip:
        assert_gige_host_subnet(device, device_ip)
    unicast_ip = _resolve_unicast_ip(interface_name, device_ip)

    handle_attempts: list[tuple[int, bytes | int, str]] = []
    if connect_ip and device.get("camera_type") == "GigE":
        handle_attempts.append(
            (IMV_ECreateHandleMode.modeByIPAddress, connect_ip.encode("utf-8"), f"IP:{connect_ip}")
        )
    camera_key = str(device.get("camera_key", "")).strip()
    if camera_key:
        handle_attempts.append(
            (IMV_ECreateHandleMode.modeByCameraKey, camera_key.encode("utf-8"), f"key:{camera_key[:24]}")
        )
    handle_attempts.append(
        (IMV_ECreateHandleMode.modeByIndex, int(device.get("index", 0)), f"index:{device.get('index')}")
    )

    last_create_ret = IMV_ERROR
    last_open_ret = IMV_ERROR
    used_mode = ""

    for mode, param, label in handle_attempts:
        _destroy_handle(cam)
        last_create_ret = _create_handle(cam, mode, param)
        if last_create_ret != IMV_OK:
            logger.debug("IMV_CreateHandle(%s) failed: %d", label, last_create_ret)
            continue
        last_open_ret = _open_camera_handle(cam)
        if last_open_ret == IMV_OK:
            used_mode = label
            break
        logger.debug("IMV_Open(%s) failed: %d", label, last_open_ret)
        _destroy_handle(cam)

    if last_open_ret != IMV_OK:
        if last_open_ret == IMV_INVALID_IP and device.get("camera_type") == "GigE":
            assert_gige_host_subnet(device, device_ip)
        raise ScannerProtocolError(f"IMV_Open failed ({imv_error_hint(last_open_ret)})")

    logger.info("Opened device via %s", used_mode or "unknown")

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
