"""Export device UserSet configuration via IMV_SaveDeviceCfg."""

from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from imv_sdk.IMVDefines import IMV_OK

from scanner.feature import try_first_command, try_first_enum
from scanner_config import (
    HARDWARE_USERSET_SYMBOLS,
    SOFTWARE_USERSET_SYMBOLS,
    USERSET_LOAD_COMMANDS,
    USERSET_SELECTOR_FEATURES,
)
from scanner_utils import ScannerProtocolError

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)

ZIP_MAGIC = b"PK\x03\x04"


def _activate_userset(cam: MvCamera, symbols: tuple[str, ...]) -> str:
    for feature in USERSET_SELECTOR_FEATURES:
        selected = try_first_enum(cam, feature, symbols)
        if selected:
            try_first_command(cam, USERSET_LOAD_COMMANDS)
            return selected
    return symbols[0]


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

    # Some models accept .xml extension directly.
    ret = cam.IMV_SaveDeviceCfg(str(xml_path.with_suffix(".xml.tmp")))
    direct_tmp = xml_path.with_suffix(".xml.tmp")
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
    Export software/hardware UserSet snapshots.

    - software_config.xml: IMV_SaveDeviceCfg after software UserSet load (XML or ZIP→XML)
    - hardware_config.mvcfg: IMV_SaveDeviceCfg binary vendor format
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}

    software_path = output_dir / "software_config.xml"
    software_symbol = _activate_userset(cam, SOFTWARE_USERSET_SYMBOLS)
    logger.info("Saving software UserSet (symbol=%s) to XML via IMV_SaveDeviceCfg", software_symbol)
    _save_device_cfg_as_xml(cam, software_path)
    outputs["software_config"] = str(software_path)

    hardware_path = output_dir / "hardware_config.mvcfg"
    hardware_symbol = _activate_userset(cam, HARDWARE_USERSET_SYMBOLS)
    logger.info("Saving hardware UserSet (symbol=%s) via IMV_SaveDeviceCfg", hardware_symbol)
    _save_device_cfg(cam, hardware_path)
    outputs["hardware_config"] = str(hardware_path)

    return outputs
