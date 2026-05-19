"""High-level scanner workflow based on pure GVCP/GVSP protocol."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genicam.accessor import GenicamAccessor
from genicam.bootstrap import fetch_genicam_xml
from genicam.config_export import export_userset_xml
from gvcp.device import GvcpDevice
from gvcp_discovery import _is_discovery_bind_ip, _iter_host_interfaces, enum_devices as gvcp_enum_devices
from gvsp.chunk_parser import parse_scan_payload
from gvsp.receiver import GvspReceiver
from gvsp.setup import configure_stream_channel
from scanner_config import (
    DEFAULT_BUFFER_COUNT,
    DEFAULT_FRAME_TIMEOUT_MS,
    FEATURE_ROOT_NAMES,
    HARDWARE_USERSET_SYMBOLS,
    SOFTWARE_USERSET_SYMBOLS,
    TRIGGER_COMMAND_FEATURES,
    TRIGGER_MODE_FEATURES,
    TRIGGER_MODE_ON_SYMBOLS,
    TRIGGER_SOURCE_FEATURES,
    TRIGGER_SOURCE_SOFTWARE_SYMBOLS,
    USERSET_LOAD_COMMANDS,
    USERSET_SELECTOR_FEATURES,
)
from scanner_utils import ScannerProtocolError, ensure_dir, save_frame_image, write_json

logger = logging.getLogger(__name__)
DISCOVERY_GVCP = "gvcp"


@dataclass
class CaptureOptions:
    timeout_ms: int = DEFAULT_FRAME_TIMEOUT_MS
    buffer_count: int = DEFAULT_BUFFER_COUNT
    clear_buffer: bool = True


class ScannerReader:
    def __init__(self) -> None:
        self.connected = False
        self.device_info: dict[str, Any] | None = None
        self.device: GvcpDevice | None = None
        self.accessor: GenicamAccessor | None = None
        self.genicam_xml_text = ""
        self.bind_ip = ""

    def enum_devices(self, interface_name: str | None = None) -> list[dict[str, Any]]:
        devices = gvcp_enum_devices()
        if interface_name:
            needle = interface_name.casefold()
            devices = [dev for dev in devices if needle in str(dev.get("interface_name", "")).casefold()]
        logger.info("Discovered %d device(s) via GVCP.", len(devices))
        return devices

    def find_device(
        self,
        *,
        serial_number: str | None = None,
        ip: str | None = None,
        interface_name: str | None = None,
    ) -> dict[str, Any]:
        target = serial_number or ip
        if not target:
            raise ValueError("Either serial_number or ip is required.")

        devices = self.enum_devices(interface_name=interface_name)
        if not devices:
            raise RuntimeError("No scanner device found (GVCP discovery).")

        matched_devices = [
            dev
            for dev in devices
            if (serial_number and dev["serial_number"] == serial_number)
            or (ip and dev["ip_address"] == ip)
        ]

        if not matched_devices:
            raise RuntimeError(f"Device not found for target={target}")

        if len(matched_devices) > 1 and not interface_name:
            interface_hint = ", ".join(
                sorted({dev["interface_name"] or "unknown" for dev in matched_devices})
            )
            raise RuntimeError(
                "Multiple devices matched target "
                f"{target} on interfaces [{interface_hint}]. "
                "Please specify --interface or run --list-devices."
            )
        return matched_devices[0]

    def connect(
        self,
        *,
        serial_number: str | None = None,
        ip: str | None = None,
        interface_name: str | None = None,
    ) -> dict[str, Any]:
        matched = self.find_device(serial_number=serial_number, ip=ip, interface_name=interface_name)
        self.bind_ip = self._resolve_bind_ip(
            device_ip=str(matched.get("ip_address", "")),
            interface_name=interface_name or str(matched.get("interface_name", "")),
        )
        if not self.bind_ip:
            raise ScannerProtocolError("Cannot resolve local bind IP. Please specify --interface correctly.")

        self.device = GvcpDevice(device_ip=str(matched["ip_address"]), bind_ip=self.bind_ip)
        bootstrap = fetch_genicam_xml(self.device)
        self.genicam_xml_text = bootstrap.xml_text
        self.accessor = GenicamAccessor(self.device, self.genicam_xml_text)
        self.connected = True
        self.device_info = dict(matched)
        self.device_info["genicam_xml_url"] = bootstrap.url
        return self.device_info

    def disconnect(self) -> None:
        if self.device is not None:
            self.device.close()
        self.device = None
        self.accessor = None
        self.connected = False

    def dump_feature_candidates(self, output_dir: Path) -> dict[str, list[str]]:
        self._ensure_connected()
        ensure_dir(output_dir)
        feature_map: dict[str, list[str]] = {}
        assert self.accessor is not None
        for root_name in FEATURE_ROOT_NAMES:
            feature_map[root_name] = self.accessor.list_feature_children(root_name)
        write_json(output_dir / "feature_dump.json", feature_map)
        return feature_map

    def export_configs(self, output_dir: Path) -> dict[str, str]:
        self._ensure_connected()
        ensure_dir(output_dir)
        outputs: dict[str, str] = {}
        software_path = output_dir / "software_config.xml"
        hardware_path = output_dir / "hardware_config.xml"

        software_symbol = self._select_userset(SOFTWARE_USERSET_SYMBOLS)
        export_userset_xml(self.genicam_xml_text, software_symbol, software_path)
        outputs["software_config"] = str(software_path)

        hardware_symbol = self._select_userset(HARDWARE_USERSET_SYMBOLS)
        export_userset_xml(self.genicam_xml_text, hardware_symbol, hardware_path)
        outputs["hardware_config"] = str(hardware_path)
        return outputs

    def capture_scan(self, output_dir: Path, options: CaptureOptions) -> dict[str, Any]:
        self._ensure_connected()
        ensure_dir(output_dir)
        assert self.device is not None
        assert self.accessor is not None
        if not self.bind_ip:
            raise ScannerProtocolError("Missing bind IP, connect first.")

        timeout_s = max(options.timeout_ms / 1000.0, 0.2)
        receiver = GvspReceiver(self.bind_ip, timeout_s=timeout_s)
        try:
            configure_stream_channel(self.device, self.bind_ip, receiver.port, accessor=self.accessor)
            self._prepare_soft_trigger()
            self._trigger_once()
            frame = receiver.capture_frame(timeout_s)
        finally:
            receiver.close()

        image_path = save_frame_image(
            output_dir / "scan_image",
            frame.image_bytes,
            is_jpeg=frame.is_jpeg,
            width=frame.width,
            height=frame.height,
        )
        chunk_payload = parse_scan_payload(frame.image_bytes)
        payload: dict[str, Any] = {
            "frame_id": 0,
            "timestamp": int(time.time() * 1_000_000_000),
            "width": frame.width,
            "height": frame.height,
            "pixel_format": 0,
            "image_data_len": len(frame.image_bytes),
            "is_jpeg": frame.is_jpeg,
            **chunk_payload,
            "image_path": str(image_path),
        }
        write_json(output_dir / "scan_result.json", payload)
        return payload

    def enum_sdk_devices_diagnostics(self) -> list[str]:
        # Pure GVCP mode: SDK enumeration removed.
        return []

    def _select_userset(self, symbols: tuple[str, ...]) -> str:
        self._ensure_connected()
        assert self.accessor is not None
        for feature in USERSET_SELECTOR_FEATURES:
            for symbol in symbols:
                if self.accessor.set_enum_symbol(feature, symbol):
                    for command in USERSET_LOAD_COMMANDS:
                        self.accessor.exec_command(command)
                    return symbol
        return symbols[0]

    def _prepare_soft_trigger(self) -> None:
        self._ensure_connected()
        assert self.accessor is not None
        for feature in TRIGGER_MODE_FEATURES:
            for symbol in TRIGGER_MODE_ON_SYMBOLS:
                if self.accessor.set_enum_symbol(feature, symbol):
                    break
        for feature in TRIGGER_SOURCE_FEATURES:
            for symbol in TRIGGER_SOURCE_SOFTWARE_SYMBOLS:
                if self.accessor.set_enum_symbol(feature, symbol):
                    break

    def _trigger_once(self) -> str:
        self._ensure_connected()
        assert self.accessor is not None
        for command in TRIGGER_COMMAND_FEATURES:
            if self.accessor.exec_command(command):
                return command
        raise ScannerProtocolError(f"Unable to trigger commands from candidates={TRIGGER_COMMAND_FEATURES}")

    def _ensure_connected(self) -> None:
        if not self.connected or self.device is None or self.accessor is None:
            raise ScannerProtocolError("Device is not connected.")

    def _resolve_bind_ip(self, *, device_ip: str, interface_name: str | None) -> str:
        interfaces = [item for item in _iter_host_interfaces() if _is_discovery_bind_ip(item.ip)]
        if interface_name:
            needle = interface_name.casefold()
            for item in interfaces:
                if needle in item.name.casefold():
                    return item.ip
        for item in interfaces:
            if device_ip and item.ip.split(".")[:3] == device_ip.split(".")[:3]:
                return item.ip
        if interfaces:
            return interfaces[0].ip
        return ""
