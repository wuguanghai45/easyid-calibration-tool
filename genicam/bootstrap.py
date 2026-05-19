"""GenICam XML bootstrap helpers over GVCP."""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass

from gvcp.device import GvcpDevice


@dataclass
class GenicamXml:
    url: str
    xml_text: str


LOCAL_URL_PATTERN = re.compile(r"^local:([^;]+);0x([0-9a-fA-F]+);0x([0-9a-fA-F]+)$")


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
        _filename, addr_hex, size_hex = local_match.groups()
        address = int(addr_hex, 16)
        size = int(size_hex, 16)
        payload = device.read_memory(address, size)
        return payload.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    if normalized.lower().startswith(("http://", "https://")):
        with urllib.request.urlopen(normalized, timeout=5) as response:  # nosec B310
            payload = response.read()
        return payload.decode("utf-8", errors="replace")

    raise RuntimeError(f"Unsupported GenICam XML URL format: {url}")

