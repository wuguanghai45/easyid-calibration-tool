"""GenICam feature helpers via IMV SDK."""

from __future__ import annotations

import logging
from ctypes import byref
from typing import TYPE_CHECKING, Any

from imv_sdk.IMVDefines import IMV_OK, IMV_String

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


def read_enum_symbol(cam: MvCamera, feature: str) -> str | None:
    if not cam.IMV_FeatureIsReadable(feature):
        return None
    symbol = IMV_String()
    if cam.IMV_GetEnumFeatureSymbol(feature, byref(symbol)) != IMV_OK:
        return None
    return symbol.str.decode("utf-8", errors="replace").strip("\x00")


def get_active_userset(cam: MvCamera, selector_features: tuple[str, ...]) -> dict[str, Any]:
    """Read the currently selected UserSet from the device."""
    for feature in selector_features:
        symbol = read_enum_symbol(cam, feature)
        if symbol is not None:
            return {"selector_feature": feature, "symbol": symbol}
    return {"selector_feature": None, "symbol": None}


def load_userset(cam: MvCamera, load_commands: tuple[str, ...]) -> bool:
    """Execute UserSetLoad for the currently selected UserSet."""
    return try_first_command(cam, load_commands) is not None
