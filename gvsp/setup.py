"""GVSP stream channel setup."""

from __future__ import annotations

import socket
import struct

from gvcp.device import GvcpDevice


def ipv4_to_u32(ipv4: str) -> int:
    return struct.unpack("!I", socket.inet_aton(ipv4))[0]


def configure_stream_channel(device: GvcpDevice, host_ip: str, host_port: int, packet_size: int = 1400) -> None:
    host_ip_u32 = ipv4_to_u32(host_ip)
    device.configure_stream_destination(host_ip_u32, host_port, packet_size=packet_size, scpd=0)

