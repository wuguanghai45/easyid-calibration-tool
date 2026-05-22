"""Logical device config fields mapped to GenICam feature names."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from scanner.feature import read_feature_field, save_userset, write_feature_field
from scanner_config import USERSET_SAVE_COMMANDS

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

CONFIG_FIELD_SPECS: dict[str, dict[str, tuple[str, ...]]] = {
    "exposure_time_us": {
        "double_candidates": ("ExposureTime", "ExposureTimeAbs"),
        "int_candidates": (),
        "enum_candidates": (),
    },
    "gain": {
        "double_candidates": ("Gain", "GainRaw"),
        "int_candidates": ("GainRaw",),
        "enum_candidates": (),
    },
    "timeout_ms": {
        "double_candidates": (),
        "int_candidates": ("AcquisitionTimeout", "ReadTimeout", "FrameTimeout"),
        "enum_candidates": (),
    },
    "trigger_mode": {
        "double_candidates": (),
        "int_candidates": (),
        "enum_candidates": ("TriggerMode", "AcquisitionTriggerMode"),
    },
    "trigger_source": {
        "double_candidates": (),
        "int_candidates": (),
        "enum_candidates": ("TriggerSource", "AcquisitionTriggerSource"),
    },
}


def read_device_config(cam: MvCamera) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    for key, spec in CONFIG_FIELD_SPECS.items():
        fields.append(read_feature_field(cam, key, **spec))
    return {"fields": fields}


def write_device_config(cam: MvCamera, updates: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for key, value in updates.items():
        spec = CONFIG_FIELD_SPECS.get(key)
        if spec is None:
            results.append({"key": key, "feature": None, "ok": False, "error": "unknown_field"})
            continue
        results.append(write_feature_field(cam, key, value, **spec))

    saved = False
    if persist:
        saved = save_userset(cam, USERSET_SAVE_COMMANDS)

    return {"results": results, "userset_saved": saved, "fields": read_device_config(cam)["fields"]}
