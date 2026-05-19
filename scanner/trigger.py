"""Soft trigger configuration for IMV cameras."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from imv_sdk.IMVDefines import IMV_OK

from scanner.feature import set_enum_symbol, try_first_command, try_first_enum
from scanner_config import (
    TRIGGER_COMMAND_FEATURES,
    TRIGGER_MODE_FEATURES,
    TRIGGER_MODE_ON_SYMBOLS,
    TRIGGER_SOURCE_FEATURES,
    TRIGGER_SOURCE_SOFTWARE_SYMBOLS,
)
from scanner_utils import ScannerProtocolError

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)


def configure_soft_trigger(cam: MvCamera) -> None:
    """Apply soft-trigger GenICam settings (SoftTrigger.py pattern)."""
    for feature in TRIGGER_MODE_FEATURES:
        if try_first_enum(cam, feature, TRIGGER_MODE_ON_SYMBOLS):
            break

    set_enum_symbol(cam, "TriggerSelector", "FrameStart")

    for feature in TRIGGER_SOURCE_FEATURES:
        if try_first_enum(cam, feature, TRIGGER_SOURCE_SOFTWARE_SYMBOLS):
            break


def fire_software_trigger(cam: MvCamera) -> str:
    command = try_first_command(cam, TRIGGER_COMMAND_FEATURES)
    if command:
        return command
    ret = cam.IMV_ExecuteCommandFeature("TriggerSoftware")
    if ret != IMV_OK:
        raise ScannerProtocolError(
            f"Unable to execute soft trigger (candidates={TRIGGER_COMMAND_FEATURES}, last={ret})"
        )
    return "TriggerSoftware"


def try_enable_chunk_mode(cam: MvCamera) -> bool:
    if not cam.IMV_FeatureIsWriteable("ChunkModeActive"):
        return False
    ret = cam.IMV_SetBoolFeatureValue("ChunkModeActive", True)
    return ret == IMV_OK
