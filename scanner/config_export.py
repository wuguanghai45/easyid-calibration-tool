"""Export UserSet configuration as GenICam XML via IMV SDK."""

from __future__ import annotations

import logging
import shutil
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


def _activate_userset(cam: MvCamera, symbols: tuple[str, ...]) -> str:
    for feature in USERSET_SELECTOR_FEATURES:
        selected = try_first_enum(cam, feature, symbols)
        if selected:
            try_first_command(cam, USERSET_LOAD_COMMANDS)
            return selected
    return symbols[0]


def _download_xml(cam: MvCamera, output_path: Path) -> None:
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()
    ret = cam.IMV_DownLoadGenICamXML(str(temp_path))
    if ret != IMV_OK:
        raise ScannerProtocolError(f"IMV_DownLoadGenICamXML failed with error code {ret} for {output_path.name}")
    if not temp_path.is_file() or temp_path.stat().st_size == 0:
        raise ScannerProtocolError(f"Downloaded GenICam XML is empty: {output_path.name}")
    shutil.move(str(temp_path), str(output_path))


def export_userset_xml(cam: MvCamera, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}

    software_path = output_dir / "software_config.xml"
    software_symbol = _activate_userset(cam, SOFTWARE_USERSET_SYMBOLS)
    logger.info("Exporting software UserSet symbol=%s", software_symbol)
    _download_xml(cam, software_path)
    outputs["software_config"] = str(software_path)

    hardware_path = output_dir / "hardware_config.xml"
    hardware_symbol = _activate_userset(cam, HARDWARE_USERSET_SYMBOLS)
    logger.info("Exporting hardware UserSet symbol=%s", hardware_symbol)
    _download_xml(cam, hardware_path)
    outputs["hardware_config"] = str(hardware_path)
    return outputs
