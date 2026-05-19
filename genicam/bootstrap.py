"""GenICam XML bootstrap helpers over GVCP."""

from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass

from gvcp.device import GvcpDevice


@dataclass
class GenicamXml:
    url: str
    xml_text: str


LOCAL_URL_PATTERN = re.compile(r"^local:([^;]+);([0-9a-fA-Fx]+);([0-9a-fA-Fx]+)$", re.IGNORECASE)


def fetch_genicam_xml(device: GvcpDevice) -> GenicamXml:
    candidates = device.read_xml_url_candidates()
    if not candidates:
        raise RuntimeError("No GenICam XML URL found from device bootstrap registers")

    last_error: Exception | None = None
    for url in candidates:
        try:
            xml_text = _fetch_single_url(device, url)
            return GenicamXml(url=url, xml_text=xml_text)
        except Exception as exc:  # pragma: no cover - device dependent
            last_error = exc
            continue
    raise RuntimeError(f"Failed to fetch GenICam XML from URL candidates={candidates}: {last_error}")


def _fetch_single_url(device: GvcpDevice, url: str) -> str:
    normalized = url.strip()
    local_match = LOCAL_URL_PATTERN.match(normalized.lower())
    if local_match:
        filename, addr_hex, size_hex = local_match.groups()
        address = _parse_hex_or_prefixed_int(addr_hex)
        size = _parse_hex_or_prefixed_int(size_hex)
        payload = device.read_memory_chunked(address, size, chunk_size=512)
        if filename.lower().endswith(".zip") or b"PK\x03\x04" in payload[:32]:
            try:
                return _decode_xml_from_zip(payload)
            except Exception:
                # Fallback for mislabeled *.zip payloads.
                return _decode_xml_text(payload)
        return _decode_xml_text(payload)

    if normalized.lower().startswith(("http://", "https://")):
        with urllib.request.urlopen(normalized, timeout=5) as response:  # nosec B310
            payload = response.read()
        return payload.decode("utf-8", errors="replace")

    raise RuntimeError(f"Unsupported GenICam XML URL format: {url}")


def _parse_hex_or_prefixed_int(value: str) -> int:
    text = value.strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    # GenICam local URL commonly uses raw hex without 0x.
    return int(text, 16)


def _decode_xml_text(payload: bytes) -> str:
    body = payload.split(b"\x00", 1)[0]
    for encoding in ("utf-8", "utf-16-le", "gbk", "latin-1"):
        try:
            return body.decode(encoding)
        except Exception:
            continue
    return body.decode("utf-8", errors="replace")


def _decode_xml_from_zip(payload: bytes) -> str:
    start = payload.find(b"PK\x03\x04")
    zipped = payload[start:] if start >= 0 else payload
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        names = archive.namelist()
        if not names:
            raise RuntimeError("Empty GenICam ZIP payload")
        xml_names = [name for name in names if name.lower().endswith(".xml")]
        target = xml_names[0] if xml_names else names[0]
        data = archive.read(target)
    return _decode_xml_text(data)

