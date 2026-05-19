"""GenICam feature helpers via IMV SDK."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from imv_sdk.IMVDefines import IMV_OK

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)


def set_enum_symbol(cam: MvCamera, feature: str, symbol: str) -> bool:
    if not cam.IMV_FeatureIsWriteable(feature):
        return False
    ret = cam.IMV_SetEnumFeatureSymbol(feature, symbol)
    if ret != IMV_OK:
        logger.debug("SetEnumFeatureSymbol(%s, %s) failed: %d", feature, symbol, ret)
        return False
    return True


def exec_command(cam: MvCamera, command: str) -> bool:
    if not cam.IMV_FeatureIsAvailable(command):
        return False
    ret = cam.IMV_ExecuteCommandFeature(command)
    if ret != IMV_OK:
        logger.debug("ExecuteCommandFeature(%s) failed: %d", command, ret)
        return False
    return True


def try_first_enum(cam: MvCamera, feature: str, symbols: tuple[str, ...]) -> str | None:
    for symbol in symbols:
        if set_enum_symbol(cam, feature, symbol):
            return symbol
    return None


def try_first_command(cam: MvCamera, commands: tuple[str, ...]) -> str | None:
    for command in commands:
        if exec_command(cam, command):
            return command
    return None
