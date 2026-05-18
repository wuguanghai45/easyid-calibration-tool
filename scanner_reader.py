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

    def connect(self, *, serial_number: str | None = None, ip: str | None = None) -> dict[str, Any]:
        target = serial_number or ip
        if not target:
            raise ValueError("Either serial_number or ip is required.")

        device_list = EasyID.EidDeviceList()
        check_ret(
            EasyID.Camera.eidEnumDevices(device_list, EasyID.EidInterfaceType.eidInterfaceTypeAll),
            "eidEnumDevices",
        )
        if device_list.num <= 0:
            raise RuntimeError("No scanner device found.")

        matched = None
        for idx in range(device_list.num):
            info = device_list.infos[idx]
            if serial_number and decode_cstr(info.serialNumber) == serial_number:
                matched = info
                break
            if ip and decode_cstr(info.gigeDeviceInfo.ipAddress) == ip:
                matched = info
                break

        if matched is None:
            raise RuntimeError(f"Device not found for target={target}")

        create_data = serial_number or ip or ""
        create_type = (
            EasyID.EidDeviceDataType.eidDeviceDataTypeSN
            if serial_number
            else EasyID.EidDeviceDataType.eidDeviceDataTypeIP
        )
        check_ret(self.camera.eidCreateDevice(create_data.encode("ascii"), create_type), "eidCreateDevice")
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
