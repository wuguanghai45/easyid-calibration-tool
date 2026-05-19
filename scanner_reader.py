"""High-level scanner workflow for calibration data collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import EasyID

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
from gvcp_discovery import discover_gige_devices
from scanner_utils import (
    check_ret,
    copy_image_bytes,
    decode_cstr,
    ensure_dir,
    exec_command_feature,
    list_feature_children,
    parse_frame_info,
    save_frame_image,
    set_enum_feature_symbol,
    write_json,
)


@dataclass
class CaptureOptions:
    timeout_ms: int = DEFAULT_FRAME_TIMEOUT_MS
    buffer_count: int = DEFAULT_BUFFER_COUNT
    clear_buffer: bool = True


class ScannerReader:
    def __init__(self) -> None:
        self.camera = EasyID.Camera()
        self.connected = False
        self.device_info: EasyID.EidDeviceInfo | None = None

    def enum_devices(self) -> list[dict[str, Any]]:
        return discover_gige_devices()

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

        devices = self.enum_devices()
        if not devices:
            raise RuntimeError("No scanner device found.")

        matched_devices = [
            dev
            for dev in devices
            if (serial_number and dev["serial_number"] == serial_number)
            or (ip and dev["ip_address"] == ip)
        ]

        if interface_name:
            needle = interface_name.casefold()
            matched_devices = [
                dev for dev in matched_devices if needle in dev["interface_name"].casefold()
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
        matched = self.find_device(
            serial_number=serial_number,
            ip=ip,
            interface_name=interface_name,
        )
        sdk_device = self.find_sdk_device(
            gvcp_matched=matched,
            serial_number=serial_number,
            ip=ip,
            interface_name=interface_name,
        )
        create_attempts = self._build_create_device_attempts(
            gvcp_matched=matched,
            sdk_device=sdk_device,
            serial_number=serial_number,
            ip=ip,
        )
        last_ret = EasyID.EidError.eidErrorInvalidParameter
        for create_data, create_type in create_attempts:
            last_ret = self.camera.eidCreateDevice(create_data, create_type)
            if last_ret == EasyID.EidError.eidErrorOK:
                break
        check_ret(last_ret, "eidCreateDevice")
        check_ret(self.camera.eidOpenDevice(), "eidOpenDevice")
        self.connected = True

        info = EasyID.EidDeviceInfo()
        check_ret(self.camera.eidGetDeviceInfo(info), "eidGetDeviceInfo")
        self.device_info = info
        return self.device_info_to_dict(info)

    def disconnect(self) -> None:
        if not self.connected:
            return
        try:
            self.camera.eidStopGrabbing()
        except Exception:
            pass
        try:
            self.camera.eidCloseDevice()
        except Exception:
            pass
        try:
            self.camera.eidReleaseHandle()
        except Exception:
            pass
        self.connected = False

    def dump_feature_candidates(self, output_dir: Path) -> dict[str, list[str]]:
        ensure_dir(output_dir)
        feature_map: dict[str, list[str]] = {}
        for root_name in FEATURE_ROOT_NAMES:
            try:
                feature_map[root_name] = list_feature_children(self.camera, root_name)
            except Exception:
                continue
        write_json(output_dir / "feature_dump.json", feature_map)
        return feature_map

    def export_configs(self, output_dir: Path) -> dict[str, str]:
        ensure_dir(output_dir)
        outputs: dict[str, str] = {}

        software_path = output_dir / "software_config.xml"
        hardware_path = output_dir / "hardware_config.xml"

        self._select_userset(SOFTWARE_USERSET_SYMBOLS)
        check_ret(self.camera.eidSaveDeviceConfig(str(software_path)), "eidSaveDeviceConfig(software)")
        outputs["software_config"] = str(software_path)

        self._select_userset(HARDWARE_USERSET_SYMBOLS)
        check_ret(self.camera.eidSaveDeviceConfig(str(hardware_path)), "eidSaveDeviceConfig(hardware)")
        outputs["hardware_config"] = str(hardware_path)
        return outputs

    def capture_scan(self, output_dir: Path, options: CaptureOptions) -> dict[str, Any]:
        ensure_dir(output_dir)
        check_ret(self.camera.eidStartGrabbing(options.buffer_count), "eidStartGrabbing")
        frame_acquired = False
        try:
            if options.clear_buffer:
                self.camera.eidClearFrameBuffer()

            self._prepare_soft_trigger()
            self._trigger_once()

            check_ret(self.camera.eidGetFrame(options.timeout_ms), "eidGetFrame")
            frame_acquired = True
            frame_info = EasyID.EidFrameInfo()
            check_ret(self.camera.eidGetFrameInfo(frame_info), "eidGetFrameInfo")

            image_bytes = copy_image_bytes(frame_info)
            image_path = save_frame_image(output_dir / "scan_image", frame_info, image_bytes)

            payload = parse_frame_info(frame_info)
            payload["image_path"] = str(image_path)
            write_json(output_dir / "scan_result.json", payload)
            return payload
        finally:
            if frame_acquired:
                try:
                    self.camera.eidReleaseFrame()
                except Exception:
                    pass
            try:
                self.camera.eidStopGrabbing()
            except Exception:
                pass

    def enum_sdk_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        for interface_type in (
            EasyID.EidInterfaceType.eidInterfaceTypeGige,
            EasyID.EidInterfaceType.eidInterfaceTypeAll,
        ):
            device_list = EasyID.EidDeviceList()
            ret = EasyID.Camera.eidEnumDevices(device_list, interface_type)
            if ret != EasyID.EidError.eidErrorOK:
                continue
            for idx in range(device_list.num):
                devices.append(self.device_info_to_dict(device_list.infos[idx]))
            if devices:
                break
        return devices

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        return "".join(ch for ch in mac if ch.isalnum()).lower()

    def find_sdk_device(
        self,
        *,
        gvcp_matched: dict[str, Any],
        serial_number: str | None,
        ip: str | None,
        interface_name: str | None,
    ) -> dict[str, Any] | None:
        try:
            sdk_devices = self.enum_sdk_devices()
        except Exception:
            return None
        if not sdk_devices:
            return None

        target_sn = serial_number or gvcp_matched.get("serial_number") or ""
        target_ip = ip or gvcp_matched.get("ip_address") or ""
        target_mac = gvcp_matched.get("mac_address") or ""
        normalized_mac = self._normalize_mac(target_mac)

        matched_devices: list[dict[str, Any]] = []
        for dev in sdk_devices:
            if target_sn and dev.get("serial_number") == target_sn:
                matched_devices.append(dev)
            elif target_ip and dev.get("ip_address") == target_ip:
                matched_devices.append(dev)
            elif normalized_mac and self._normalize_mac(dev.get("mac_address", "")) == normalized_mac:
                matched_devices.append(dev)

        if interface_name:
            needle = interface_name.casefold()
            matched_devices = [
                dev
                for dev in matched_devices
                if needle in str(dev.get("interface_name", "")).casefold()
            ]

        if not matched_devices:
            return None
        return matched_devices[0]

    @classmethod
    def _build_create_device_attempts(
        cls,
        *,
        gvcp_matched: dict[str, Any],
        sdk_device: dict[str, Any] | None,
        serial_number: str | None,
        ip: str | None,
    ) -> list[tuple[str, int]]:
        """Build ordered eidCreateDevice attempts; CLI args take priority over SDK device_id."""
        attempts: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()

        def add(value: str | None, data_type: int) -> None:
            normalized = (value or "").strip()
            if not normalized:
                return
            key = (normalized, data_type)
            if key in seen:
                return
            seen.add(key)
            attempts.append(key)

        # User-specified identifiers first (SDK manual default is serial number; IP is common for --ip).
        if ip:
            add(ip, EasyID.EidDeviceDataType.eidDeviceDataTypeIP)
        if serial_number:
            add(serial_number, EasyID.EidDeviceDataType.eidDeviceDataTypeSN)

        for source in (sdk_device, gvcp_matched):
            if not source:
                continue
            add(source.get("serial_number"), EasyID.EidDeviceDataType.eidDeviceDataTypeSN)
            add(source.get("ip_address"), EasyID.EidDeviceDataType.eidDeviceDataTypeIP)
            add(source.get("mac_address"), EasyID.EidDeviceDataType.eidDeviceDataTypeMAC)
            add(source.get("device_id"), EasyID.EidDeviceDataType.eidDeviceDataTypeID)

        if not attempts:
            raise RuntimeError("Matched device has no usable identifier (device_id/sn/ip/mac).")
        return attempts

    @staticmethod
    def device_info_to_dict(info: EasyID.EidDeviceInfo) -> dict[str, Any]:
        return {
            "device_id": decode_cstr(info.deviceID),
            "camera_name": decode_cstr(info.cameraName),
            "serial_number": decode_cstr(info.serialNumber),
            "vendor_name": decode_cstr(info.vendorName),
            "model_name": decode_cstr(info.modelName),
            "manufacture_info": decode_cstr(info.manufactureInfo),
            "device_version": decode_cstr(info.deviceVersion),
            "interface_name": decode_cstr(info.interfaceName),
            "device_type": int(info.deviceType),
            "interface_type": int(info.interfaceType),
            "ip_address": decode_cstr(info.gigeDeviceInfo.ipAddress),
            "subnet_mask": decode_cstr(info.gigeDeviceInfo.subnetMask),
            "gateway": decode_cstr(info.gigeDeviceInfo.defaultGateWay),
            "mac_address": decode_cstr(info.gigeDeviceInfo.macAddress),
        }

    def _select_userset(self, symbols: tuple[str, ...]) -> None:
        set_enum_feature_symbol(
            self.camera,
            USERSET_SELECTOR_FEATURES,
            symbols,
        )
        try:
            exec_command_feature(self.camera, USERSET_LOAD_COMMANDS)
        except Exception:
            # Some models apply selector immediately without load command.
            pass

    def _prepare_soft_trigger(self) -> None:
        try:
            set_enum_feature_symbol(self.camera, TRIGGER_MODE_FEATURES, TRIGGER_MODE_ON_SYMBOLS)
        except Exception:
            pass
        try:
            set_enum_feature_symbol(
                self.camera,
                TRIGGER_SOURCE_FEATURES,
                TRIGGER_SOURCE_SOFTWARE_SYMBOLS,
            )
        except Exception:
            pass

    def _trigger_once(self) -> None:
        exec_command_feature(self.camera, TRIGGER_COMMAND_FEATURES)
