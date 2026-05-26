"""Import device UserSet configuration via IMV_LoadDeviceCfg."""

from __future__ import annotations

import logging
from ctypes import byref, memset, sizeof
from pathlib import Path
from typing import TYPE_CHECKING, Any

from imv_sdk.IMVDefines import IMV_ErrorList, IMV_OK

from scanner.device_config import read_device_config
from scanner.feature import save_userset
from scanner_config import USERSET_SAVE_COMMANDS, resolve_camera_config_path
from scanner_utils import ScannerProtocolError

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)


def _is_xml_bytes(data: bytes) -> bool:
    stripped = data.lstrip()
    return stripped.startswith(b"<?xml") or stripped.startswith(b"<")


def _validate_config_file(config_path: Path) -> Path:
    resolved = config_path.resolve()
    if not resolved.is_file():
        raise ScannerProtocolError(f"Camera config file not found: {resolved}")
    data = resolved.read_bytes()
    if not data:
        raise ScannerProtocolError(f"Camera config file is empty: {resolved.name}")
    if not _is_xml_bytes(data):
        raise ScannerProtocolError(
            f"Camera config file is not XML: {resolved.name}. "
            "Expected device configuration exported by IMV_SaveDeviceCfg."
        )
    return resolved


def _parse_failed_params(error_list: IMV_ErrorList) -> list[str]:
    count = int(error_list.nParamCnt)
    if count <= 0:
        return []
    failed: list[str] = []
    for index in range(count):
        name = error_list.paramNameList[index].str.decode("utf-8", errors="replace").strip("\x00")
        if name:
            failed.append(name)
    return failed


def load_device_config(
    cam: MvCamera,
    config_path: Path | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Load device configuration from XML via IMV_LoadDeviceCfg.

    Optionally persists with UserSetSave and returns read-back GenICam fields.
    """
    path = _validate_config_file(config_path or resolve_camera_config_path())
    logger.info("Loading camera config from %s", path)

    error_list = IMV_ErrorList()
    memset(byref(error_list), 0, sizeof(IMV_ErrorList))
    ret = cam.IMV_LoadDeviceCfg(str(path), error_list)
    failed_params = _parse_failed_params(error_list)

    if ret != IMV_OK:
        detail = f"IMV_LoadDeviceCfg failed with error code {ret}"
        if failed_params:
            detail += f"; failed params: {', '.join(failed_params[:8])}"
            if len(failed_params) > 8:
                detail += f" (+{len(failed_params) - 8} more)"
        raise ScannerProtocolError(detail)

    if failed_params:
        logger.warning(
            "IMV_LoadDeviceCfg succeeded with %d parameter(s) not applied: %s",
            len(failed_params),
            ", ".join(failed_params[:16]),
        )

    userset_saved = False
    if persist:
        userset_saved = save_userset(cam, USERSET_SAVE_COMMANDS)
        if not userset_saved:
            logger.warning("UserSetSave failed after config import")

    readback = read_device_config(cam)
    return {
        "config_path": str(path),
        "userset_saved": userset_saved,
        "failed_params": failed_params,
        "fields": readback["fields"],
    }
