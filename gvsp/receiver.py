"""Simple GVSP UDP frame receiver."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass


@dataclass
class GvspFrame:
    image_bytes: bytes
    is_jpeg: bool
    width: int = 0
    height: int = 0
    timestamp_ns: int = 0


class GvspReceiver:
    def __init__(self, bind_ip: str, timeout_s: float = 2.0) -> None:
        self.bind_ip = bind_ip
        self.timeout_s = timeout_s
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout_s)
        self.sock.bind((bind_ip, 0))
        self.port = self.sock.getsockname()[1]

    def close(self) -> None:
        self.sock.close()

    def capture_frame(self, capture_timeout_s: float) -> GvspFrame:
        deadline = time.monotonic() + capture_timeout_s
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            timeout_left = max(deadline - time.monotonic(), 0.05)
            self.sock.settimeout(timeout_left)
            try:
                packet, _addr = self.sock.recvfrom(65535)
            except socket.timeout:
                break
            if len(packet) <= 8:
                continue
            # Strip 8-byte GVSP header and keep payload bytes.
            chunks.append(packet[8:])

        payload = b"".join(chunks)
        if not payload:
            return GvspFrame(image_bytes=b"", is_jpeg=False)
        jpeg = _extract_jpeg(payload)
        if jpeg is not None:
            return GvspFrame(image_bytes=jpeg, is_jpeg=True)
        return GvspFrame(image_bytes=payload, is_jpeg=False)


def _extract_jpeg(payload: bytes) -> bytes | None:
    start = payload.find(b"\xFF\xD8")
    if start < 0:
        return None
    end = payload.rfind(b"\xFF\xD9")
    if end < 0 or end <= start:
        return None
    return payload[start : end + 2]

