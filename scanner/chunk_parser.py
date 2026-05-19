"""Parse barcode metadata from IMV frame chunk data."""

from __future__ import annotations

import json
import re
from ctypes import string_at
from typing import Any, TYPE_CHECKING

from imv_sdk.IMVDefines import IMV_ChunkDataInfo, IMV_Frame, IMV_OK, IMV_String

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        result = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if isinstance(result, dict):
        return result
    return None


def _payload_from_text(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "read_state": 0,
        "read_state_name": "unknown",
        "code_num": 0,
        "codes": [],
    }
    if not text:
        return payload

    parsed_json = _extract_json_object(text)
    if isinstance(parsed_json, dict):
        codes = parsed_json.get("codes") or parsed_json.get("barcodes") or []
        if isinstance(codes, list):
            payload["codes"] = codes
            payload["code_num"] = len(codes)
        if "read_state" in parsed_json:
            payload["read_state"] = int(parsed_json["read_state"])
            payload["read_state_name"] = "ok" if payload["read_state"] == 0 else "error"
        return payload

    candidates = re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-_/]{7,}", text)
    if candidates:
        unique = sorted(set(candidates))[:16]
        payload["codes"] = [{"data": item} for item in unique]
        payload["code_num"] = len(unique)
        payload["read_state_name"] = "heuristic"
    return payload


def parse_frame_chunks(cam: MvCamera, frame: IMV_Frame) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "read_state": 0,
        "read_state_name": "unknown",
        "code_num": 0,
        "codes": [],
        "chunk_params": [],
    }
    chunk_count = int(frame.frameInfo.chunkCount)
    if chunk_count <= 0:
        return payload

    collected_text: list[str] = []
    for index in range(chunk_count):
        chunk_info = IMV_ChunkDataInfo()
        ret = cam.IMV_GetChunkDataByIndex(frame, index, chunk_info)
        if ret != IMV_OK:
            continue
        for param_index in range(int(chunk_info.nParamCnt)):
            param = chunk_info.pParamNameList[param_index]
            name = param.str.decode("utf-8", errors="replace").strip("\x00")
            payload["chunk_params"].append({"name": name, "chunk_id": int(chunk_info.chunkID)})
            collected_text.append(name)

    merged = "\n".join(collected_text)
    parsed = _payload_from_text(merged)
    payload.update({key: parsed[key] for key in ("read_state", "read_state_name", "code_num", "codes")})
    return payload


def parse_frame_bytes(frame_bytes: bytes) -> dict[str, Any]:
    """Fallback parser when chunk metadata is unavailable."""
    return _payload_from_text(frame_bytes.decode("utf-8", errors="ignore"))


def frame_pixel_bytes(frame: IMV_Frame) -> bytes:
    size = int(frame.frameInfo.size)
    if size <= 0 or not frame.pData:
        return b""
    return bytes(string_at(frame.pData, size))
