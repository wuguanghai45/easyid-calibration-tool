"""Export device UserSet configuration via IMV_SaveDeviceCfg."""

from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from imv_sdk.IMVDefines import IMV_OK

from scanner.feature import (
    get_active_userset,
    load_userset,
    try_first_command,
    try_first_enum,
)
from scanner_config import (
    HARDWARE_USERSET_SYMBOLS,
    SOFTWARE_USERSET_SYMBOLS,
    USERSET_LOAD_COMMANDS,
    USERSET_SELECTOR_FEATURES,
)
from scanner_utils import ScannerProtocolError, write_json

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)

ZIP_MAGIC = b"PK\x03\x04"


def _activate_userset(cam: MvCamera, symbols: tuple[str, ...]) -> dict[str, Any]:
    """Select a UserSet symbol, load it, and read back the active selection."""
    for feature in USERSET_SELECTOR_FEATURES:
        selected = try_first_enum(cam, feature, symbols)
        if not selected:
            continue
        if not try_first_command(cam, USERSET_LOAD_COMMANDS):
            logger.warning("UserSetLoad failed after selecting %s on %s", selected, feature)
        active = get_active_userset(cam, USERSET_SELECTOR_FEATURES)
        return {
            "selector_feature": feature,
            "requested_symbol": selected,
            "active_symbol": active.get("symbol"),
        }

    active = get_active_userset(cam, USERSET_SELECTOR_FEATURES)
    return {
        "selector_feature": active.get("selector_feature"),
        "requested_symbol": None,
        "active_symbol": active.get("symbol"),
    }


def _sync_active_userset(cam: MvCamera) -> dict[str, Any]:
    """Read current UserSetSelector and load that group before exporting."""
    active = get_active_userset(cam, USERSET_SELECTOR_FEATURES)
    if not active.get("symbol"):
        logger.warning("Cannot read UserSetSelector; exporting without explicit UserSetLoad.")
        return active

    logger.info(
        "Current UserSet: %s=%s, loading before export",
        active.get("selector_feature"),
        active.get("symbol"),
    )
    if not load_userset(cam, USERSET_LOAD_COMMANDS):
        logger.warning("UserSetLoad failed for active UserSet %s", active.get("symbol"))
    return active


def _is_xml_bytes(data: bytes) -> bool:
    stripped = data.lstrip()
    return stripped.startswith(b"<?xml") or stripped.startswith(b"<")


def _extract_largest_xml_from_zip(zip_path: Path) -> bytes:
    with zipfile.ZipFile(zip_path, "r") as archive:
        xml_members = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if not xml_members:
            raise ScannerProtocolError(f"No XML inside configuration archive: {zip_path.name}")
        xml_members.sort(key=lambda name: archive.getinfo(name).file_size, reverse=True)
        return archive.read(xml_members[0])


def _promote_to_xml(downloaded: Path, xml_path: Path) -> None:
    data = downloaded.read_bytes()
    if not data:
        raise ScannerProtocolError(f"Configuration file is empty: {xml_path.name}")

    if _is_xml_bytes(data):
        xml_path.write_bytes(data)
        return

    if data[:4].startswith(ZIP_MAGIC):
        zip_path = xml_path.with_suffix(".zip")
        zip_path.write_bytes(data)
        xml_path.write_bytes(_extract_largest_xml_from_zip(zip_path))
        return

    raise ScannerProtocolError(
        f"Cannot produce XML for {xml_path.name}: SDK output is not XML or ZIP. "
        "Check device firmware or save format support."
    )


def _save_device_cfg(cam: MvCamera, output_path: Path) -> None:
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    ret = cam.IMV_SaveDeviceCfg(str(temp_path))
    if ret != IMV_OK:
        raise ScannerProtocolError(f"IMV_SaveDeviceCfg failed with error code {ret} for {output_path.name}")
    if not temp_path.is_file() or temp_path.stat().st_size == 0:
        raise ScannerProtocolError(f"Saved device configuration is empty: {output_path.name}")

    shutil.move(str(temp_path), str(output_path))


def _save_device_cfg_as_xml(cam: MvCamera, xml_path: Path) -> None:
    """Save active UserSet via IMV_SaveDeviceCfg and normalize to .xml."""
    temp_path = xml_path.with_name(f"{xml_path.stem}_save.tmp")
    if temp_path.exists():
        temp_path.unlink()

    direct_tmp = xml_path.with_suffix(".xml.tmp")
    ret = cam.IMV_SaveDeviceCfg(str(direct_tmp))
    if ret == IMV_OK and direct_tmp.is_file() and direct_tmp.stat().st_size > 0:
        try:
            _promote_to_xml(direct_tmp, xml_path)
            return
        except ScannerProtocolError:
            logger.debug("Direct .xml SaveDeviceCfg output is not XML; retrying generic save.")
        finally:
            direct_tmp.unlink(missing_ok=True)

    ret = cam.IMV_SaveDeviceCfg(str(temp_path))
    if ret != IMV_OK:
        raise ScannerProtocolError(f"IMV_SaveDeviceCfg failed with error code {ret} for {xml_path.name}")
    if not temp_path.is_file() or temp_path.stat().st_size == 0:
        raise ScannerProtocolError(f"Saved device configuration is empty: {xml_path.name}")

    try:
        _promote_to_xml(temp_path, xml_path)
    finally:
        temp_path.unlink(missing_ok=True)


def export_device_configs(cam: MvCamera, output_dir: Path) -> dict[str, str]:
    """
    Export software/hardware UserSet snapshots as XML.

    Flow:
    1. Read and load the currently active UserSet (UserSetSelector + UserSetLoad)
    2. Switch to target UserSet, load again, verify active symbol, then IMV_SaveDeviceCfg → XML
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}

    active_before = _sync_active_userset(cam)
    userset_info: dict[str, Any] = {"active_before_export": active_before, "exports": []}

    software_path = output_dir / "software_config.xml"
    software_activation = _activate_userset(cam, SOFTWARE_USERSET_SYMBOLS)
    software_active = get_active_userset(cam, USERSET_SELECTOR_FEATURES)
    logger.info(
        "Software export: requested=%s active=%s",
        software_activation.get("requested_symbol"),
        software_active.get("symbol"),
    )
    if software_active.get("symbol"):
        load_userset(cam, USERSET_LOAD_COMMANDS)
    _save_device_cfg_as_xml(cam, software_path)
    outputs["software_config"] = str(software_path)
    userset_info["exports"].append(
        {
            "target": "software",
            "activation": software_activation,
            "active_before_save": software_active,
        }
    )

    hardware_path = output_dir / "hardware_config.xml"
    hardware_activation = _activate_userset(cam, HARDWARE_USERSET_SYMBOLS)
    hardware_active = get_active_userset(cam, USERSET_SELECTOR_FEATURES)
    logger.info(
        "Hardware export: requested=%s active=%s",
        hardware_activation.get("requested_symbol"),
        hardware_active.get("symbol"),
    )
    if hardware_active.get("symbol"):
        load_userset(cam, USERSET_LOAD_COMMANDS)
    _save_device_cfg_as_xml(cam, hardware_path)
    outputs["hardware_config"] = str(hardware_path)
    userset_info["exports"].append(
        {
            "target": "hardware",
            "activation": hardware_activation,
            "active_before_save": hardware_active,
        }
    )

    active_after = get_active_userset(cam, USERSET_SELECTOR_FEATURES)
    userset_info["active_after_export"] = active_after
    write_json(output_dir / "userset_info.json", userset_info)
    outputs["userset_info"] = str(output_dir / "userset_info.json")

    return outputs
