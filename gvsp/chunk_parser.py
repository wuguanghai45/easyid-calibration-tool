"""Best-effort parser for vendor chunk data from GVSP payload."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_scan_payload(frame_bytes: bytes) -> dict[str, Any]:
    """Parse read-state and barcode-like metadata from raw frame bytes.

    Vendor chunk layouts are not publicly documented; this parser keeps output
    schema stable and extracts obvious JSON/text chunks when present.
    """
    payload: dict[str, Any] = {
        "read_state": 0,
        "read_state_name": "unknown",
        "code_num": 0,
        "codes": [],
    }
    if not frame_bytes:
        return payload

    text = frame_bytes.decode("utf-8", errors="ignore")
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

    # Fallback: pick likely barcode strings.
    candidates = re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-_/]{7,}", text)
    if candidates:
        unique = sorted(set(candidates))[:16]
        payload["codes"] = [{"data": item} for item in unique]
        payload["code_num"] = len(unique)
        payload["read_state_name"] = "heuristic"
    return payload


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        result = json.loads(text[start : end + 1])
    except Exception:
        return None
    if isinstance(result, dict):
        return result
    return None

