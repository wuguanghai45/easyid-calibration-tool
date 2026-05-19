"""GVSP stream channel setup."""

from __future__ import annotations

import logging
import socket
import struct

from gvcp.device import GvcpDevice

logger = logging.getLogger(__name__)


def ipv4_to_u32(ipv4: str) -> int:
    return struct.unpack("!I", socket.inet_aton(ipv4))[0]


def configure_stream_channel(
    device: GvcpDevice,
    host_ip: str,
    host_port: int,
    packet_size: int = 1400,
    accessor: object | None = None,
) -> None:
    host_ip_u32 = ipv4_to_u32(host_ip)
    configured = False

    # Preferred path: write stream params using GenICam node names from XML.
    if accessor is not None and hasattr(accessor, "set_integer_feature"):
        configured |= _set_int_feature(accessor, ("GevSCPSPacketSize",), packet_size)
        configured |= _set_int_feature(accessor, ("GevSCPHostPort",), host_port)
        configured |= _set_int_feature(accessor, ("GevSCPD",), 0)
        # Some devices expose either GevSCDA or GevSCDA1.
        configured |= _set_int_feature(accessor, ("GevSCDA", "GevSCDA1"), host_ip_u32)
        if configured:
            logger.info("GVSP stream configured via GenICam features.")
            return

    # Fallback: legacy bootstrap register addresses (may fail on some devices).
    try:
        device.configure_stream_destination(host_ip_u32, host_port, packet_size=packet_size, scpd=0)
        logger.info("GVSP stream configured via bootstrap registers.")
    except Exception as exc:
        logger.warning("GVSP bootstrap register config failed: %s", exc)
        if not configured:
            raise


def _set_int_feature(accessor: object, names: tuple[str, ...], value: int) -> bool:
    setter = getattr(accessor, "set_integer_feature", None)
    if setter is None:
        return False
    for name in names:
        try:
            if bool(setter(name, value)):
                return True
        except Exception:
            continue
    return False

