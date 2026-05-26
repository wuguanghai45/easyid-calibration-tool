"""High-level scanner workflow based on IMV MVSDK."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scanner.capture import capture_soft_trigger_frame
from scanner.config_export import export_device_configs
from scanner.config_import import load_device_config
from scanner.device import (
    close_camera,
    enum_devices,
    find_device,
    open_camera,
    refresh_device_via_unicast,
)
from scanner.feature_dump import dump_readable_features
from scanner.gige_network import (
    ensure_target_ip,
    host_has_factory_subnet,
    needs_ip_update,
    recover_gige_to_host_subnet,
)
from scanner_config import (
    DEFAULT_BUFFER_COUNT,
    DEFAULT_FRAME_TIMEOUT_MS,
    TARGET_DEVICE_IP,
)
from scanner_utils import ScannerProtocolError, ensure_dir, write_json

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)


@dataclass
class CaptureOptions:
    timeout_ms: int = DEFAULT_FRAME_TIMEOUT_MS
    buffer_count: int = DEFAULT_BUFFER_COUNT
    clear_buffer: bool = True


class ScannerReader:
    def __init__(self) -> None:
        self.connected = False
        self.device_info: dict[str, Any] | None = None
        self.cam: MvCamera | None = None
        self._interface_name: str | None = None

    def enum_devices(self, interface_name: str | None = None) -> list[dict[str, Any]]:
        devices = enum_devices()
        if interface_name:
            from scanner.device import _filter_by_interface

            devices = _filter_by_interface(devices, interface_name)
        return devices

    def find_device(
        self,
        *,
        serial_number: str | None = None,
        ip: str | None = None,
        interface_name: str | None = None,
    ) -> dict[str, Any]:
        devices = self.enum_devices(interface_name=interface_name)
        return find_device(devices, serial_number=serial_number, ip=ip, interface_name=interface_name)

    def connect(
        self,
        *,
        serial_number: str | None = None,
        ip: str | None = None,
        interface_name: str | None = None,
    ) -> dict[str, Any]:
        logger.info("Scanning devices...")
        matched = self.find_device(serial_number=serial_number, ip=ip, interface_name=interface_name)
        self._interface_name = interface_name

        ip_meta: dict[str, Any] = {
            "ip_before": str(matched.get("ip_address", "")),
            "ip_after": str(matched.get("ip_address", "")),
            "ip_reconfigured": False,
            "ip_recovered": False,
        }

        device_ip = str(matched.get("ip_address", ""))
        if (
            matched.get("camera_type") == "GigE"
            and device_ip == TARGET_DEVICE_IP
            and not host_has_factory_subnet()
        ):
            result = recover_gige_to_host_subnet(matched)
            matched = result["device"]
            ip_meta.update(
                {
                    "ip_before": result["ip_before"],
                    "ip_after": result["ip_after"],
                    "ip_recovered": result["ip_recovered"],
                    "recovery_host_ip": result.get("recovery_host_ip"),
                }
            )

        if needs_ip_update(matched, TARGET_DEVICE_IP):
            if host_has_factory_subnet():
                logger.info(
                    "IP mismatch, reconfiguring to %s (gateway/subnet from factory defaults)",
                    TARGET_DEVICE_IP,
                )
                result = ensure_target_ip(matched)
                matched = result["device"]
                ip_meta = {
                    "ip_before": result["ip_before"],
                    "ip_after": result["ip_after"],
                    "ip_reconfigured": result["ip_reconfigured"],
                    "ip_recovered": False,
                }
            else:
                logger.warning(
                    "Device IP is %s (not factory %s) and host has no 192.168.40.x address; "
                    "continuing on current subnet. Add 192.168.40.x on the camera NIC to apply factory IP.",
                    device_ip,
                    TARGET_DEVICE_IP,
                )
            sn = serial_number or str(matched.get("serial_number", ""))
            if sn and (ip_meta.get("ip_reconfigured") or ip_meta.get("ip_recovered")):
                devices = self.enum_devices(interface_name=interface_name)
                matched = find_device(
                    devices,
                    serial_number=sn,
                    interface_name=interface_name,
                )

        connect_ip = ip
        if ip_meta.get("ip_reconfigured"):
            connect_ip = TARGET_DEVICE_IP
        elif ip_meta.get("ip_recovered"):
            connect_ip = str(matched.get("ip_address", "")) or connect_ip

        if matched.get("camera_type") == "GigE":
            from scanner.device import assert_gige_host_subnet

            assert_gige_host_subnet(matched, str(matched.get("ip_address", "")))
            if ip_meta.get("ip_reconfigured") or ip_meta.get("ip_recovered"):
                matched = refresh_device_via_unicast(
                    matched,
                    serial_number=serial_number or str(matched.get("serial_number", "")) or None,
                    ip=connect_ip,
                    interface_name=interface_name,
                )

        self.cam, self.device_info = open_camera(
            matched,
            serial_number=serial_number or str(matched.get("serial_number", "")) or None,
            ip=connect_ip,
            interface_name=interface_name,
        )
        self.device_info.update(ip_meta)
        self.connected = True
        return self.device_info

    def disconnect(self) -> None:
        close_camera(self.cam)
        self.cam = None
        self.connected = False

    def dump_feature_candidates(self, output_dir: Path) -> dict[str, list[str]]:
        self._ensure_connected()
        ensure_dir(output_dir)
        assert self.cam is not None
        feature_map = dump_readable_features(self.cam)
        write_json(output_dir / "feature_dump.json", feature_map)
        return feature_map

    def export_configs(self, output_dir: Path) -> dict[str, str]:
        self._ensure_connected()
        assert self.cam is not None
        return export_device_configs(self.cam, output_dir)

    def import_device_config(
        self,
        config_path: Path | None = None,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        self._ensure_connected()
        assert self.cam is not None
        return load_device_config(self.cam, config_path, persist=persist)

    def capture_scan(self, output_dir: Path, options: CaptureOptions) -> dict[str, Any]:
        self._ensure_connected()
        assert self.cam is not None
        payload = capture_soft_trigger_frame(
            self.cam,
            output_dir,
            timeout_ms=options.timeout_ms,
            buffer_count=options.buffer_count,
            clear_buffer=options.clear_buffer,
        )
        write_json(output_dir / "scan_result.json", payload)
        return payload

    def get_sdk_version(self) -> str:
        try:
            from imv_sdk.IMVApi import MvCamera as _MvCamera

            version = _MvCamera.IMV_GetVersion()
            if version:
                return version.decode("utf-8", errors="replace")
        except Exception:
            pass
        return "unknown"

    def _ensure_connected(self) -> None:
        if not self.connected or self.cam is None:
            raise ScannerProtocolError("Device is not connected.")
