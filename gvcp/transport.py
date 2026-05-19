"""GVCP UDP transport client."""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from .packet import (
    GVCP_ACK_READMEM,
    GVCP_ACK_READREG,
    GVCP_ACK_WRITEMEM,
    GVCP_ACK_WRITEREG,
    GVCP_CMD_READMEM,
    GVCP_CMD_READREG,
    GVCP_CMD_WRITEMEM,
    GVCP_CMD_WRITEREG,
    build_cmd,
    parse_ack,
)


class GvcpError(RuntimeError):
    """Raised on GVCP transport/protocol errors."""


@dataclass
class GvcpClient:
    device_ip: str
    bind_ip: str
    port: int = 3956
    timeout_s: float = 1.0

    def __post_init__(self) -> None:
        self._request_id = 1
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self.timeout_s)
        self._sock.bind((self.bind_ip, 0))

    def close(self) -> None:
        self._sock.close()

    def read_register(self, address: int) -> int:
        payload = struct.pack("!I", address & 0xFFFFFFFF)
        ack_payload = self._request_response(GVCP_CMD_READREG, GVCP_ACK_READREG, payload)
        if len(ack_payload) < 4:
            raise GvcpError("READREG ack payload too short")
        return struct.unpack_from("!I", ack_payload, 0)[0]

    def write_register(self, address: int, value: int) -> None:
        payload = struct.pack("!II", address & 0xFFFFFFFF, value & 0xFFFFFFFF)
        self._request_response(GVCP_CMD_WRITEREG, GVCP_ACK_WRITEREG, payload)

    def read_memory(self, address: int, size: int) -> bytes:
        payload = struct.pack("!II", address & 0xFFFFFFFF, size & 0xFFFFFFFF)
        ack_payload = self._request_response(GVCP_CMD_READMEM, GVCP_ACK_READMEM, payload)
        if len(ack_payload) <= 4:
            return b""
        # Some devices may return more bytes than requested in a single ACK.
        # Keep exactly requested size to avoid caller-side offset drift.
        return ack_payload[4:][:size]

    def write_memory(self, address: int, data: bytes) -> None:
        payload = struct.pack("!I", address & 0xFFFFFFFF) + data
        self._request_response(GVCP_CMD_WRITEMEM, GVCP_ACK_WRITEMEM, payload)

    def _request_response(self, cmd: int, expect_ack: int, payload: bytes) -> bytes:
        request_id = self._request_id
        self._request_id = (self._request_id + 1) & 0xFFFF
        packet = build_cmd(cmd, payload, request_id)
        self._sock.sendto(packet, (self.device_ip, self.port))
        response, _ = self._sock.recvfrom(65535)
        status, ack_type, ack_payload = parse_ack(response)
        if ack_type != expect_ack:
            raise GvcpError(f"Unexpected ack type: expected 0x{expect_ack:04X}, got 0x{ack_type:04X}")
        if status != 0:
            raise GvcpError(f"GVCP command failed: status={status}")
        return ack_payload

