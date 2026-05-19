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
        payload = device.read_memory_chunked(address, size, chunk_size=0x200)
        if filename.lower().endswith(".zip") or b"PK\x03\x04" in payload[:32]:
            try:
                return _decode_xml_from_zip(payload)
            except Exception:
                pass
        try:
            return _decode_xml_text(payload)
        except Exception:
            pass
        # Fallback: some devices expose local file through HTTP endpoint.
        for suffix in (filename, f"xml/{filename}", f"XML/{filename}"):
            try:
                with urllib.request.urlopen(f"http://{device.device_ip}/{suffix}", timeout=5) as response:  # nosec B310
                    body = response.read()
                if filename.lower().endswith(".zip") or body.startswith(b"PK\x03\x04"):
                    try:
                        return _decode_xml_from_zip(body)
                    except Exception:
                        pass
                return _decode_xml_text(body)
            except Exception:
                continue
        raise RuntimeError(f"Failed to fetch local GenICam resource: {url}")

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
    body = _extract_xml_bytes(payload)
    for encoding in ("utf-8-sig", "utf-8", "utf-16-le", "utf-16-be", "gbk"):
        try:
            text = body.decode(encoding)
            if _looks_like_xml_text(text):
                return text
        except Exception:
            continue
    raise RuntimeError("Unable to decode valid GenICam XML text from payload")


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


def _extract_xml_bytes(payload: bytes) -> bytes:
    """Trim binary wrappers and keep only XML document bytes."""
    if not payload:
        return payload
    # Prefer explicit XML declaration.
    start = payload.find(b"<?xml")
    if start < 0:
        # Some files start directly with root element.
        for marker in (b"<RegisterDescription", b"<RegisterDescriptionModel", b"<Docu"):
            start = payload.find(marker)
            if start >= 0:
                break
    if start < 0:
        # Keep as-is; caller will attempt multi-encoding decode and validation.
        return payload

    xml_part = payload[start:]
    # Try to cut at common closing tags to remove trailing binary tail.
    for end_marker in (b"</RegisterDescription>", b"</RegisterDescriptionModel>", b"</Docu>"):
        end = xml_part.find(end_marker)
        if end >= 0:
            return xml_part[: end + len(end_marker)]
    return xml_part


def _looks_like_xml_text(text: str) -> bool:
    if not text:
        return False
    candidate = text.lstrip("\ufeff\x00 \t\r\n")
    if not candidate:
        return False
    if not candidate.startswith("<"):
        return False
    return (
        "<?xml" in candidate[:200]
        or "<RegisterDescription" in candidate[:400]
        or "<RegisterDescriptionModel" in candidate[:400]
    )

