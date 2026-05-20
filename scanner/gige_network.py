"""GigE device IP configuration via IMV SDK."""

from __future__ import annotations

import logging
import time
from ctypes import byref, c_void_p
from typing import TYPE_CHECKING, Any

from imv_sdk.IMVDefines import IMV_ECreateHandleMode, IMV_OK

from scanner.device import close_camera, enum_devices
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


def _create_handle_by_index(cam: MvCamera, index: int) -> None:
    ret = cam.IMV_CreateHandle(IMV_ECreateHandleMode.modeByIndex, byref(c_void_p(index)))
    if ret != IMV_OK:
        raise ScannerProtocolError(f"IMV_CreateHandle failed with error code {ret}")


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

    logger.info(
        "GigE IP mismatch: current=%s target=%s, reconfiguring (SN=%s)",
        ip_before,
        target_ip,
        serial_number or "unknown",
    )

    cam = MvCamera()
    try:
        _create_handle_by_index(cam, index)
        force_ip_address(cam, target_ip, subnet_mask, gateway)

        ret = cam.IMV_Open()
        if ret != IMV_OK:
            raise ScannerProtocolError(f"IMV_Open failed after ForceIp (error code {ret})")

        persist_gige_ip(cam, target_ip, subnet_mask, gateway)
    finally:
        close_camera(cam)

    logger.info("Waiting %.1fs for GigE network to settle after IP change", settle_sec)
    time.sleep(settle_sec)

    devices = enum_devices()
    refreshed = None
    if serial_number:
        for item in devices:
            if item.get("serial_number") == serial_number:
                refreshed = item
                break
    if refreshed is None:
        for item in devices:
            if item.get("ip_address") == target_ip:
                refreshed = item
                break

    if refreshed is None:
        raise ScannerProtocolError(
            f"Device not found after IP change to {target_ip}. "
            "Ensure the host NIC is on the factory subnet (e.g. 192.168.40.x/24)."
        )

    return {
        "ip_before": ip_before,
        "ip_after": target_ip,
        "ip_reconfigured": True,
        "device": refreshed,
    }
