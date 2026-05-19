"""High-level scanner workflow based on IMV MVSDK."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scanner.capture import capture_soft_trigger_frame
from scanner.config_export import export_userset_xml
from scanner.device import close_camera, enum_devices, find_device, open_camera
from scanner.feature_dump import dump_readable_features
from scanner_config import DEFAULT_BUFFER_COUNT, DEFAULT_FRAME_TIMEOUT_MS
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
        matched = self.find_device(serial_number=serial_number, ip=ip, interface_name=interface_name)
        self._interface_name = interface_name
        self.cam, self.device_info = open_camera(
            matched,
            serial_number=serial_number,
            ip=ip,
            interface_name=interface_name,
        )
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
        return export_userset_xml(self.cam, output_dir)

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
