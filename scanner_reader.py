"""High-level scanner workflow for calibration data collection."""

from __future__ import annotations

import logging
from ctypes import POINTER, cast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import EasyID

from gige_host import configure_gige_discovery_host, resolve_bind_ip, try_easyid_bind_exports
from gvcp_discovery import enum_devices as gvcp_enum_devices
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
    ERROR_CODE_NAMES,
    EasyIDOperationError,
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

logger = logging.getLogger(__name__)
MAX_DEVICE_NUM = getattr(EasyID, "MAX_DEVICE_NUM", 256)
DISCOVERY_GVCP = "gvcp"
DISCOVERY_SDK = "sdk"


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

    def enum_devices(self, interface_name: str | None = None) -> list[dict[str, Any]]:
        """Discover devices via GVCP (replaces SDK ``eidEnumDevices`` in this tool)."""
        devices = gvcp_enum_devices()
        if interface_name:
            needle = interface_name.casefold()
            devices = [
                dev
                for dev in devices
                if needle in str(dev.get("interface_name", "")).casefold()
            ]
        logger.info("Discovered %d device(s) via GVCP (eidEnumDevices not used).", len(devices))
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
        matched = self.find_device(
            serial_number=serial_number,
            ip=ip,
            interface_name=interface_name,
        )
        logger.info(
            "GVCP matched device: ip=%s sn=%s interface=%s",
            matched.get("ip_address"),
            matched.get("serial_number"),
            matched.get("interface_name"),
        )

        self._prepare_gige_host(
            device_ip=ip or matched.get("ip_address"),
            interface_name=interface_name or matched.get("interface_name"),
        )

        # Optional: SDK enum may add device_id; GVCP is sufficient for discovery.
        sdk_device = self._try_match_sdk_device(
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
            type_name = self._device_data_type_name(create_type)
            logger.info("eidCreateDevice: data=%r type=%s", create_data, type_name)
            last_ret = self.camera.eidCreateDevice(create_data, create_type)
            if last_ret == EasyID.EidError.eidErrorOK:
                break

        if last_ret != EasyID.EidError.eidErrorOK:
            raise EasyIDOperationError(
                "eidCreateDevice failed after GVCP discovery: "
                f"{ERROR_CODE_NAMES.get(last_ret, 'unknown')} ({last_ret}). "
                "Device was found by GVCP but SDK could not open it. "
                "Check GigE driver (Drivers folder), EASYID_RUNENV_64, and try --sn."
            )

        check_ret(self.camera.eidOpenDevice(), "eidOpenDevice")
        self.connected = True

        info = EasyID.EidDeviceInfo()
        check_ret(self.camera.eidGetDeviceInfo(info), "eidGetDeviceInfo")
        self.device_info = info
        return self.device_info_to_dict(info)

    def _prepare_gige_host(
        self,
        *,
        device_ip: str | None,
        interface_name: str | None,
    ) -> None:
        bind_ip = resolve_bind_ip(device_ip=device_ip, interface_name=interface_name)
        if not bind_ip:
            logger.warning(
                "Could not resolve host bind IP for interface=%r; "
                "eidCreateDevice may fail on multi-homed PCs.",
                interface_name,
            )
            return
        sdk_root = getattr(EasyID, "EASYID_SDK_ROOT", None)
        for line in configure_gige_discovery_host(bind_ip, sdk_root):
            logger.debug("%s", line)
        for line in try_easyid_bind_exports(EasyID.EASYID, bind_ip):
            logger.debug("%s", line)

    def _try_match_sdk_device(
        self,
        *,
        gvcp_matched: dict[str, Any],
        serial_number: str | None,
        ip: str | None,
        interface_name: str | None,
    ) -> dict[str, Any] | None:
        try:
            sdk_devices = self.enum_sdk_devices()
        except Exception as exc:
            logger.debug("SDK eidEnumDevices skipped: %s", exc)
            return None
        if not sdk_devices:
            logger.debug("SDK eidEnumDevices returned 0 devices (GVCP discovery used instead).")
            return None
        logger.info("SDK eidEnumDevices returned %d device(s) (optional enrichment).", len(sdk_devices))
        return self._match_sdk_device(
            sdk_devices,
            gvcp_matched=gvcp_matched,
            serial_number=serial_number,
            ip=ip,
            interface_name=interface_name,
        )

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
        """Optional SDK transport enumeration (often returns empty; use ``enum_devices`` instead)."""
        EasyID.initialize_runtime()
        devices, _logs = self._enum_sdk_devices_internal(log_each_attempt=False)
        for dev in devices:
            dev["discovery"] = DISCOVERY_SDK
        return devices

    def enum_sdk_devices_diagnostics(self) -> list[str]:
        EasyID.initialize_runtime()
        _devices, logs = self._enum_sdk_devices_internal(log_each_attempt=True)
        return logs

    def _enum_sdk_devices_internal(self, *, log_each_attempt: bool) -> tuple[list[dict[str, Any]], list[str]]:
        devices: list[dict[str, Any]] = []
        logs: list[str] = []
        seen: set[str] = set()
        interface_types = (
            EasyID.EidInterfaceType.eidInterfaceTypeGige,
            0,
            EasyID.EidInterfaceType.eidInterfaceTypeAll,
        )
        layouts: tuple[tuple[str, type], ...] = (
            ("pointer+prealloc", EasyID.EidDeviceList),
            ("pointer", EasyID.EidDeviceList),
            ("inline", EasyID.EidDeviceListInline),
        )

        for layout_name, list_type in layouts:
            for interface_type in interface_types:
                for preallocate in (True, False) if layout_name != "inline" else (False,):
                    device_list = list_type()
                    backing = None
                    if layout_name == "pointer+prealloc":
                        backing = (EasyID.EidDeviceInfo * MAX_DEVICE_NUM)()
                        device_list.infos = cast(backing, POINTER(EasyID.EidDeviceInfo))

                    ret = EasyID.Camera.eidEnumDevices(device_list, interface_type)
                    count = min(int(device_list.num), MAX_DEVICE_NUM)
                    log_line = (
                        f"sdk_enum layout={layout_name} iface=0x{interface_type & 0xFFFFFFFF:08X} "
                        f"prealloc={preallocate} ret={ret} num={count}"
                    )
                    logs.append(log_line)
                    if log_each_attempt:
                        logger.info(log_line)

                    if ret != EasyID.EidError.eidErrorOK or count == 0:
                        continue

                    for idx in range(count):
                        if layout_name == "inline":
                            info = device_list.infos[idx]
                        elif backing is not None:
                            info = backing[idx]
                        elif device_list.infos:
                            info = device_list.infos[idx]
                        else:
                            break
                        dev = self.device_info_to_dict(info)
                        key = dev.get("serial_number") or dev.get("ip_address") or dev.get("device_id")
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        devices.append(dev)
                    if devices:
                        return devices, logs
        return devices, logs

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        return "".join(ch for ch in mac if ch.isalnum()).lower()

    def _match_sdk_device(
        self,
        sdk_devices: list[dict[str, Any]],
        *,
        gvcp_matched: dict[str, Any],
        serial_number: str | None,
        ip: str | None,
        interface_name: str | None,
    ) -> dict[str, Any] | None:
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
        """Build eidCreateDevice attempts from GVCP discovery (primary) and optional SDK enum."""
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

        def add_mac(value: str | None) -> None:
            normalized = (value or "").strip()
            if not normalized:
                return
            add(normalized, EasyID.EidDeviceDataType.eidDeviceDataTypeMAC)
            add(normalized.replace(":", ""), EasyID.EidDeviceDataType.eidDeviceDataTypeMAC)
            add(normalized.replace(":", "").upper(), EasyID.EidDeviceDataType.eidDeviceDataTypeMAC)

        # GVCP discovery (replaces eidEnumDevices for device identification).
        add(gvcp_matched.get("serial_number"), EasyID.EidDeviceDataType.eidDeviceDataTypeSN)
        add(gvcp_matched.get("ip_address"), EasyID.EidDeviceDataType.eidDeviceDataTypeIP)
        add_mac(gvcp_matched.get("mac_address"))

        if serial_number:
            add(serial_number, EasyID.EidDeviceDataType.eidDeviceDataTypeSN)
        if ip:
            add(ip, EasyID.EidDeviceDataType.eidDeviceDataTypeIP)

        if sdk_device:
            add(sdk_device.get("serial_number"), EasyID.EidDeviceDataType.eidDeviceDataTypeSN)
            add(sdk_device.get("device_id"), EasyID.EidDeviceDataType.eidDeviceDataTypeID)
            add(sdk_device.get("ip_address"), EasyID.EidDeviceDataType.eidDeviceDataTypeIP)
            add_mac(sdk_device.get("mac_address"))

        if not attempts:
            raise RuntimeError("Matched device has no usable identifier (sn/ip/mac).")
        return attempts

    @staticmethod
    def _device_data_type_name(data_type: int) -> str:
        mapping = {
            EasyID.EidDeviceDataType.eidDeviceDataTypeID: "ID",
            EasyID.EidDeviceDataType.eidDeviceDataTypeSN: "SN",
            EasyID.EidDeviceDataType.eidDeviceDataTypeIP: "IP",
            EasyID.EidDeviceDataType.eidDeviceDataTypeMAC: "MAC",
        }
        return mapping.get(data_type, str(data_type))

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
            "discovery": DISCOVERY_SDK,
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
