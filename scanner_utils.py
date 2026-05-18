"""Helper utilities for EasyID scanner data collection."""

from __future__ import annotations

import ctypes
import json
from pathlib import Path
from typing import Any, Iterable

import EasyID

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None


class EasyIDOperationError(RuntimeError):
    """Raised when an EasyID SDK call returns non-zero error code."""


ERROR_CODE_NAMES = {
    value: key
    for key, value in EasyID.EidError.__dict__.items()
    if not key.startswith("_")
}

READ_STATE_NAMES = {
    value: key
    for key, value in EasyID.EidReadState.__dict__.items()
    if not key.startswith("_")
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def decode_cstr(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    if isinstance(raw, str):
        return raw
    return bytes(raw).split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def check_ret(ret_code: int, action: str) -> None:
    if ret_code == EasyID.EidError.eidErrorOK:
        return
    error_name = ERROR_CODE_NAMES.get(ret_code, "eidErrorUnknown")
    raise EasyIDOperationError(f"{action} failed: {error_name} ({ret_code})")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


def copy_image_bytes(frame_info: EasyID.EidFrameInfo) -> bytes:
    if not frame_info.imageData or frame_info.imageDataLen == 0:
        return b""
    return ctypes.string_at(frame_info.imageData, frame_info.imageDataLen)


def parse_code_info(code: EasyID.EidCodeInfo) -> dict[str, Any]:
    points = [[code.position[i].x, code.position[i].y] for i in range(4)]
    return {
        "type": int(code.type),
        "type_name": decode_cstr(code.typeName),
        "data": decode_cstr(code.data),
        "ppm": float(code.ppm),
        "position": points,
    }


def parse_frame_info(frame_info: EasyID.EidFrameInfo) -> dict[str, Any]:
    codes: list[dict[str, Any]] = []
    if frame_info.codeNum > 0 and bool(frame_info.codeList):
        for idx in range(frame_info.codeNum):
            codes.append(parse_code_info(frame_info.codeList[idx]))

    return {
        "frame_id": int(frame_info.id),
        "timestamp": int(frame_info.timestamp),
        "width": int(frame_info.width),
        "height": int(frame_info.height),
        "pixel_format": int(frame_info.format),
        "read_state": int(frame_info.readState),
        "read_state_name": READ_STATE_NAMES.get(
            int(frame_info.readState),
            "eidReadStateUnknown",
        ),
        "code_num": int(frame_info.codeNum),
        "image_data_len": int(frame_info.imageDataLen),
        "is_jpeg": bool(frame_info.isJpeg),
        "codes": codes,
    }


def save_frame_image(base_path: Path, frame_info: EasyID.EidFrameInfo, image_bytes: bytes) -> Path:
    if not image_bytes:
        raw_path = base_path.with_suffix(".bin")
        raw_path.write_bytes(image_bytes)
        return raw_path

    if frame_info.isJpeg:
        jpg_path = base_path.with_suffix(".jpg")
        jpg_path.write_bytes(image_bytes)
        return jpg_path

    if Image is not None and int(frame_info.format) == int(EasyID.EidPixelFormat.eidPixelMono8):
        png_path = base_path.with_suffix(".png")
        image = Image.frombytes("L", (int(frame_info.width), int(frame_info.height)), image_bytes)
        image.save(png_path)
        return png_path

    raw_path = base_path.with_suffix(".raw")
    raw_path.write_bytes(image_bytes)
    return raw_path


def set_enum_feature_symbol(
    camera: EasyID.Camera,
    feature_names: Iterable[str],
    symbol_names: Iterable[str],
) -> tuple[str, str]:
    for feature in feature_names:
        if not camera.eidIsFeatureValid(feature):
            continue
        if not camera.eidIsFeatureWriteable(feature):
            continue
        for symbol in symbol_names:
            ret = camera.eidSetEnumFeatureSymbol(feature, symbol)
            if ret == EasyID.EidError.eidErrorOK:
                return feature, symbol
    raise EasyIDOperationError(
        f"Unable to set enum feature. features={list(feature_names)}, symbols={list(symbol_names)}"
    )


def exec_command_feature(camera: EasyID.Camera, command_names: Iterable[str]) -> str:
    for command_name in command_names:
        if not camera.eidIsFeatureValid(command_name):
            continue
        ret = camera.eidExecCommandFeature(command_name)
        if ret == EasyID.EidError.eidErrorOK:
            return command_name
    raise EasyIDOperationError(f"Unable to execute command from candidates={list(command_names)}")


def list_feature_children(camera: EasyID.Camera, root_name: str) -> list[str]:
    names: list[str] = []

    def _collector(raw_name: bytes, _user_data: Any) -> None:
        names.append(decode_cstr(raw_name))

    callback = EasyID.EidEnumFeatureChildrenCallback(_collector)
    ret = camera.eidEnumFeatureChildren(root_name, callback, None)
    check_ret(ret, f"eidEnumFeatureChildren({root_name})")
    return sorted(set(names))
