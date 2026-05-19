"""GVCP packet encode/decode utilities."""

from __future__ import annotations

import struct

GVCP_KEY = 0x42
GVCP_FLAG_ACK_REQUIRED = 0x11

GVCP_CMD_DISCOVERY = 0x0002
GVCP_ACK_DISCOVERY = 0x0003
GVCP_CMD_READREG = 0x0080
GVCP_ACK_READREG = 0x0081
GVCP_CMD_WRITEREG = 0x0082
GVCP_ACK_WRITEREG = 0x0083
GVCP_CMD_READMEM = 0x0084
GVCP_ACK_READMEM = 0x0085
GVCP_CMD_WRITEMEM = 0x0086
GVCP_ACK_WRITEMEM = 0x0087


def build_cmd(cmd: int, payload: bytes, request_id: int) -> bytes:
    return struct.pack("!BBHHH", GVCP_KEY, GVCP_FLAG_ACK_REQUIRED, cmd, len(payload), request_id & 0xFFFF) + payload


def parse_ack(packet: bytes) -> tuple[int, int, bytes]:
    """Return (status, ack_type, payload)."""
    if len(packet) < 8:
        raise ValueError("GVCP ack packet too short")
    status, ack_type, payload_len, _request_id = struct.unpack_from("!HHHH", packet, 0)
    payload = packet[8 : 8 + payload_len]
    return status, ack_type, payload

