"""Dump readable GenICam features for debugging."""

from __future__ import annotations

from typing import TYPE_CHECKING

from imv_sdk.IMVDefines import IMV_OK, IMV_String

from scanner_config import FEATURE_ROOT_NAMES, USERSET_SELECTOR_FEATURES

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera


def dump_readable_features(cam: MvCamera) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    candidates = list(FEATURE_ROOT_NAMES) + list(USERSET_SELECTOR_FEATURES)
    for name in candidates:
        flags: list[str] = []
        if cam.IMV_FeatureIsAvailable(name):
            flags.append("available")
        if cam.IMV_FeatureIsReadable(name):
            flags.append("readable")
        if cam.IMV_FeatureIsWriteable(name):
            flags.append("writeable")
        if flags:
            result[name] = flags

    for feature in USERSET_SELECTOR_FEATURES:
        if not cam.IMV_FeatureIsReadable(feature):
            continue
        symbol = IMV_String()
        if cam.IMV_GetEnumFeatureSymbol(feature, symbol) == IMV_OK:
            current = symbol.str.decode("utf-8", errors="replace").strip("\x00")
            result.setdefault(feature, []).append(f"current={current}")
    return result
