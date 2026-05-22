"""GenICam feature helpers via IMV SDK."""

from __future__ import annotations

import logging
from ctypes import byref, c_double, c_int64
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
    if cam.IMV_GetEnumFeatureSymbol(feature, symbol) != IMV_OK:
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


def save_userset(cam: MvCamera, save_commands: tuple[str, ...]) -> bool:
    """Execute UserSetSave for the currently selected UserSet."""
    return try_first_command(cam, save_commands) is not None


def find_readable_feature(cam: MvCamera, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if cam.IMV_FeatureIsReadable(name):
            return name
    return None


def find_writable_feature(cam: MvCamera, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if cam.IMV_FeatureIsWriteable(name):
            return name
    return None


def read_double_value(cam: MvCamera, feature: str) -> float | None:
    if not cam.IMV_FeatureIsReadable(feature):
        return None
    value = c_double(0.0)
    if cam.IMV_GetDoubleFeatureValue(feature, value) != IMV_OK:
        return None
    return float(value.value)


def write_double_value(cam: MvCamera, feature: str, value: float) -> bool:
    if not cam.IMV_FeatureIsWriteable(feature):
        return False
    return cam.IMV_SetDoubleFeatureValue(feature, float(value)) == IMV_OK


def read_int_value(cam: MvCamera, feature: str) -> int | None:
    if not cam.IMV_FeatureIsReadable(feature):
        return None
    value = c_int64(0)
    if cam.IMV_GetIntFeatureValue(feature, value) != IMV_OK:
        return None
    return int(value.value)


def write_int_value(cam: MvCamera, feature: str, value: int) -> bool:
    if not cam.IMV_FeatureIsWriteable(feature):
        return False
    return cam.IMV_SetIntFeatureValue(feature, int(value)) == IMV_OK


def read_feature_field(
    cam: MvCamera,
    key: str,
    *,
    double_candidates: tuple[str, ...] = (),
    int_candidates: tuple[str, ...] = (),
    enum_candidates: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Read one logical config field with candidate GenICam names."""
    feature: str | None = None
    value: Any = None
    writable = False
    value_type = "none"

    for name in double_candidates:
        if cam.IMV_FeatureIsReadable(name):
            feature = name
            value = read_double_value(cam, name)
            writable = cam.IMV_FeatureIsWriteable(name)
            value_type = "double"
            break

    if feature is None:
        for name in int_candidates:
            if cam.IMV_FeatureIsReadable(name):
                feature = name
                value = read_int_value(cam, name)
                writable = cam.IMV_FeatureIsWriteable(name)
                value_type = "int"
                break

    if feature is None:
        for name in enum_candidates:
            symbol = read_enum_symbol(cam, name)
            if symbol is not None:
                feature = name
                value = symbol
                writable = cam.IMV_FeatureIsWriteable(name)
                value_type = "enum"
                break

    return {
        "key": key,
        "feature": feature,
        "value": value,
        "writable": writable,
        "value_type": value_type,
    }


def write_feature_field(
    cam: MvCamera,
    key: str,
    value: Any,
    *,
    double_candidates: tuple[str, ...] = (),
    int_candidates: tuple[str, ...] = (),
    enum_candidates: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Write one logical config field; returns result metadata."""
    feature = find_writable_feature(cam, double_candidates)
    if feature is not None:
        ok = write_double_value(cam, feature, float(value))
        return {"key": key, "feature": feature, "ok": ok, "value_type": "double"}

    feature = find_writable_feature(cam, int_candidates)
    if feature is not None:
        ok = write_int_value(cam, feature, int(value))
        return {"key": key, "feature": feature, "ok": ok, "value_type": "int"}

    feature = find_writable_feature(cam, enum_candidates)
    if feature is not None and isinstance(value, str):
        ok = set_enum_symbol(cam, feature, value)
        return {"key": key, "feature": feature, "ok": ok, "value_type": "enum"}

    return {"key": key, "feature": None, "ok": False, "value_type": "none"}
