"""GigE device IP configuration via IMV SDK."""

from __future__ import annotations

import logging
import time
from ctypes import byref, c_void_p
from typing import TYPE_CHECKING, Any

from imv_sdk.IMVDefines import IMV_ECreateHandleMode, IMV_INVALID_IP, IMV_OK

from scanner.device import (
    close_camera,
    enum_devices,
    find_local_ip_for_device,
    select_camera_host_ip,
)
from scanner_config import (
    GIGE_IP_SETTLE_SEC,
    TARGET_DEVICE_IP,
    TARGET_GATEWAY,
    TARGET_SUBNET_MASK,
)
from scanner_utils import ScannerProtocolError

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)


def host_has_factory_subnet() -> bool:
    return find_local_ip_for_device(TARGET_DEVICE_IP) is not None


def needs_ip_update(device: dict[str, Any], target_ip: str = TARGET_DEVICE_IP) -> bool:
    if device.get("camera_type") != "GigE":
        return False
    current_ip = str(device.get("ip_address", "")).strip()
    return bool(current_ip) and current_ip != target_ip


def force_ip_address(
    cam: MvCamera,
    ip: str,
    subnet_mask: str,
    gateway: str,
) -> None:
    ret = cam.IMV_GIGE_ForceIpAddress(ip, subnet_mask, gateway)
    if ret != IMV_OK:
        raise ScannerProtocolError(
            f"IMV_GIGE_ForceIpAddress failed (ip={ip}, code={ret})"
        )


def persist_gige_ip(
    cam: MvCamera,
    ip: str,
    subnet_mask: str,
    gateway: str,
) -> None:
    ret = cam.IMV_SetBoolFeatureValue("GevCurrentIPConfigurationPersistentIP", True)
    if ret != IMV_OK:
        raise ScannerProtocolError(
            f"Set GevCurrentIPConfigurationPersistentIP failed with error code {ret}"
        )

    for feature, value in (
        ("GevPersistentIPAddress", ip),
        ("GevPersistentSubnetMask", subnet_mask),
        ("GevPersistentDefaultGateway", gateway),
    ):
        ret = cam.IMV_SetStringFeatureValue(feature, value)
        if ret != IMV_OK:
            raise ScannerProtocolError(f"Set {feature} failed with error code {ret}")


def _find_refreshed_device(
    devices: list[dict[str, Any]],
    *,
    serial_number: str,
    target_ip: str,
) -> dict[str, Any] | None:
    if serial_number:
        for item in devices:
            if item.get("serial_number") == serial_number:
                return item
    for item in devices:
        if item.get("ip_address") == target_ip:
            return item
    return None


def _enum_after_ip_change(target_ip: str) -> list[dict[str, Any]]:
    bind_ip = find_local_ip_for_device(target_ip)
    if bind_ip:
        logger.info("Re-enumerating via unicast on local %s", bind_ip)
        unicast_devices = enum_devices(unicast_ip=bind_ip)
        if unicast_devices:
            return unicast_devices
        logger.info("Unicast re-enumeration returned no devices; using global enumeration")
    return enum_devices()


def _create_handle_by_index(cam: MvCamera, index: int) -> None:
    ret = cam.IMV_CreateHandle(IMV_ECreateHandleMode.modeByIndex, byref(c_void_p(index)))
    if ret != IMV_OK:
        raise ScannerProtocolError(f"IMV_CreateHandle failed with error code {ret}")


def recover_gige_to_host_subnet(
    device: dict[str, Any],
    *,
    host_ip: str | None = None,
    settle_sec: float = GIGE_IP_SETTLE_SEC,
) -> dict[str, Any]:
    """
    ForceIp the device onto the host's current /24 (e.g. 192.168.30.200).

    Used when the device was left on the factory IP but the PC has no 192.168.40.x address.
    Does not change persistent Gev settings (session recovery only).
    """
    from imv_sdk.IMVApi import MvCamera

    chosen_host = host_ip or select_camera_host_ip()
    if not chosen_host:
        raise ScannerProtocolError("No host IPv4 available for GigE subnet recovery.")

    octets = chosen_host.split(".")
    if len(octets) != 4:
        raise ScannerProtocolError(f"Invalid host IPv4 for recovery: {chosen_host}")

    recovered_ip = f"{octets[0]}.{octets[1]}.{octets[2]}.200"
    gateway = f"{octets[0]}.{octets[1]}.{octets[2]}.1"
    ip_before = str(device.get("ip_address", ""))
    serial_number = str(device.get("serial_number", ""))
    index = int(device.get("index", 0))

    logger.warning(
        "Recovering GigE device %s -> %s (host %s, gateway %s) so IMV can connect on the current subnet",
        ip_before,
        recovered_ip,
        chosen_host,
        gateway,
    )

    cam = MvCamera()
    try:
        _create_handle_by_index(cam, index)
        force_ip_address(cam, recovered_ip, TARGET_SUBNET_MASK, gateway)
    finally:
        close_camera(cam)

    logger.info("Waiting %.1fs after GigE recovery ForceIp", settle_sec)
    time.sleep(settle_sec)

    devices = _enum_after_ip_change(recovered_ip)
    refreshed = _find_refreshed_device(
        devices,
        serial_number=serial_number,
        target_ip=recovered_ip,
    )
    if refreshed is None:
        raise ScannerProtocolError(
            f"Device not found after recovery to {recovered_ip}. "
            f"Host IPv4 on camera link: {chosen_host}."
        )

    return {
        "ip_before": ip_before,
        "ip_after": recovered_ip,
        "ip_recovered": True,
        "recovery_host_ip": chosen_host,
        "device": refreshed,
    }


def ensure_target_ip(
    device: dict[str, Any],
    *,
    target_ip: str = TARGET_DEVICE_IP,
    subnet_mask: str = TARGET_SUBNET_MASK,
    gateway: str = TARGET_GATEWAY,
    settle_sec: float = GIGE_IP_SETTLE_SEC,
) -> dict[str, Any]:
    """
    Reconfigure a GigE device to the factory target IP and persist settings.

    Returns metadata dict with ip_before, ip_after, and updated device fields.
    """
    from imv_sdk.IMVApi import MvCamera

    ip_before = str(device.get("ip_address", ""))
    serial_number = str(device.get("serial_number", ""))
    index = int(device.get("index", 0))

    if not host_has_factory_subnet():
        raise ScannerProtocolError(
            f"Cannot set factory IP {target_ip}: host has no address on 192.168.40.0/24. "
            f"Add e.g. 192.168.40.10/24 on the camera NIC, or run without factory IP change "
            f"(device will stay on {ip_before})."
        )

    logger.info(
        "GigE IP mismatch: current=%s target=%s, reconfiguring (SN=%s)",
        ip_before,
        target_ip,
        serial_number or "unknown",
    )

    cam = MvCamera()
    cross_subnet = not find_local_ip_for_device(ip_before)
    try:
        _create_handle_by_index(cam, index)
        ret = cam.IMV_Open()

        if ret == IMV_OK and not cross_subnet:
            # Host and device share a subnet: persist, then ForceIp.
            persist_gige_ip(cam, target_ip, subnet_mask, gateway)
            close_camera(cam)
            cam = MvCamera()
            _create_handle_by_index(cam, index)
            force_ip_address(cam, target_ip, subnet_mask, gateway)
            logger.info("ForceIp applied (%s -> %s)", ip_before, target_ip)
            close_camera(cam)
            cam = None
        elif ret == IMV_INVALID_IP or cross_subnet:
            # e.g. device 192.168.30.x, host only 192.168.40.x — ForceIp first, then Open+persist.
            if not host_has_factory_subnet():
                raise ScannerProtocolError(
                    f"IMV_Open failed (code {ret}): device at {ip_before} is unreachable. "
                    f"Add a host address on the device subnet or on 192.168.40.0/24."
                )
            logger.info(
                "Device at %s not reachable from host; ForceIp to %s before Open/persist",
                ip_before,
                target_ip,
            )
            if cam.IMV_IsOpen():
                cam.IMV_Close()
            force_ip_address(cam, target_ip, subnet_mask, gateway)
            close_camera(cam)
            cam = None

            logger.info("Waiting %.1fs for GigE network after ForceIp", settle_sec)
            time.sleep(settle_sec)

            devices = _enum_after_ip_change(target_ip)
            refreshed = _find_refreshed_device(
                devices,
                serial_number=serial_number,
                target_ip=target_ip,
            )
            if refreshed is None:
                raise ScannerProtocolError(
                    f"Device not found after ForceIp to {target_ip}. "
                    f"Ensure host has 192.168.40.x on the camera NIC."
                )

            cam = MvCamera()
            _create_handle_by_index(cam, int(refreshed["index"]))
            ret = cam.IMV_Open()
            if ret != IMV_OK:
                raise ScannerProtocolError(
                    f"IMV_Open failed after ForceIp to {target_ip} (error code {ret})"
                )
            persist_gige_ip(cam, target_ip, subnet_mask, gateway)
            close_camera(cam)
            cam = None

            return {
                "ip_before": ip_before,
                "ip_after": target_ip,
                "ip_reconfigured": True,
                "device": refreshed,
            }
        else:
            raise ScannerProtocolError(f"IMV_Open failed before IP change (error code {ret})")
    finally:
        if cam is not None:
            close_camera(cam)

    logger.info("Waiting %.1fs for GigE network to settle after IP change", settle_sec)
    time.sleep(settle_sec)

    devices = _enum_after_ip_change(target_ip)
    refreshed = _find_refreshed_device(
        devices,
        serial_number=serial_number,
        target_ip=target_ip,
    )

    if refreshed is None:
        raise ScannerProtocolError(
            f"Device not found after IP change to {target_ip}. "
            f"Configure the host NIC on the factory subnet (e.g. {gateway.rsplit('.', 1)[0]}.x/24) "
            f"and retry. Persistent settings were already written."
        )

    return {
        "ip_before": ip_before,
        "ip_after": target_ip,
        "ip_reconfigured": True,
        "device": refreshed,
    }
