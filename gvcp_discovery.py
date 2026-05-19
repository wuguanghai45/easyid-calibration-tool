"""GigE Vision GVCP discovery (UDP/3956) for enumerating GigE devices."""

from __future__ import annotations

import ipaddress
import locale
import re
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

GVCP_PORT = 3956
GVCP_MSG_KEY_CODE = 0x42
GVCP_FLAG_ACK_REQUIRED = 0x11
GVCP_DISCOVERY_CMD = 0x0002
GVCP_DISCOVERY_ACK = 0x0003
DISCOVERY_ACK_PAYLOAD_SIZE = 248
DEFAULT_DISCOVERY_TIMEOUT_S = 1.0


@dataclass(frozen=True)
class HostInterface:
    name: str
    ip: str
    broadcast: str


def build_discovery_command(request_id: int = 1) -> bytes:
    return struct.pack(
        "!BBHHH",
        GVCP_MSG_KEY_CODE,
        GVCP_FLAG_ACK_REQUIRED,
        GVCP_DISCOVERY_CMD,
        0,
        request_id & 0xFFFF,
    )


def _decode_padded_ip(raw: bytes) -> str:
    if len(raw) < 4:
        return ""
    return socket.inet_ntoa(raw[-4:])


def _decode_cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _format_mac(mac_bytes: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in mac_bytes)


def parse_discovery_ack(packet: bytes) -> dict[str, Any] | None:
    if len(packet) < 8:
        return None

    status, ack, _length, _req_id = struct.unpack_from("!HHHH", packet, 0)
    if status != 0 or ack != GVCP_DISCOVERY_ACK:
        return None

    payload = packet[8:]
    if len(payload) < DISCOVERY_ACK_PAYLOAD_SIZE:
        return None

    (
        _spec_version,
        _device_mode,
        mac_field,
        _supported_ip_config,
        _current_ip_config,
        current_ip_raw,
        subnet_raw,
        gateway_raw,
        manufacturer_raw,
        model_raw,
        version_raw,
        manufacture_info_raw,
        serial_raw,
        user_name_raw,
    ) = struct.unpack_from("!II8sII16s16s16s32s32s32s48s16s16s", payload, 0)

    mac_address = _format_mac(mac_field[:6])
    return {
        "mac_address": mac_address,
        "ip_address": _decode_padded_ip(current_ip_raw),
        "subnet_mask": _decode_padded_ip(subnet_raw),
        "gateway": _decode_padded_ip(gateway_raw),
        "vendor_name": _decode_cstr(manufacturer_raw),
        "model_name": _decode_cstr(model_raw),
        "device_version": _decode_cstr(version_raw),
        "manufacture_info": _decode_cstr(manufacture_info_raw),
        "serial_number": _decode_cstr(serial_raw),
        "camera_name": _decode_cstr(user_name_raw),
    }


def _is_discovery_bind_ip(ip: str) -> bool:
    """Return True if the address can be bound for GVCP discovery."""
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return not (addr.is_loopback or addr.is_link_local or addr.is_unspecified)


def _broadcast_from_ip_mask(ip: str, mask: str) -> str | None:
    try:
        interface = ipaddress.IPv4Interface(f"{ip}/{mask}")
    except ValueError:
        return None
    return str(interface.network.broadcast_address)


def _iter_host_interfaces() -> list[HostInterface]:
    if sys.platform == "win32":
        return _iter_host_interfaces_windows()
    return _iter_host_interfaces_unix()


def _iter_host_interfaces_unix() -> list[HostInterface]:
    try:
        proc = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return []

    if proc.returncode != 0:
        return []

    interfaces: list[HostInterface] = []
    for line in proc.stdout.splitlines():
        match = re.search(
            r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s",
            line,
        )
        if not match:
            continue
        name, ip, prefix = match.groups()
        if not _is_discovery_bind_ip(ip):
            continue
        try:
            network = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
        except ValueError:
            continue
        interfaces.append(
            HostInterface(
                name=name,
                ip=ip,
                broadcast=str(network.broadcast_address),
            )
        )
    return interfaces


def _windows_console_encoding() -> str:
    preferred = locale.getpreferredencoding(False) or "utf-8"
    if sys.platform == "win32" and preferred.lower().startswith("utf"):
        return "cp936"
    return preferred


def _iter_host_interfaces_windows_powershell() -> list[HostInterface]:
    script = (
        "Get-NetIPAddress -AddressFamily IPv4 | "
        "Where-Object { "
        "$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' "
        "} | ForEach-Object { "
        "$nic = Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex "
        "-AddressFamily IPv4 -ErrorAction SilentlyContinue; "
        "if ($nic -and $nic.ConnectionState -eq 'Connected') { "
        "$_.InterfaceAlias + '|' + $_.IPAddress + '|' + $_.PrefixLength "
        "} }"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
            encoding=_windows_console_encoding(),
            errors="replace",
            check=False,
        )
    except Exception:
        return []

    if proc.returncode != 0:
        return []

    interfaces: list[HostInterface] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 3:
            continue
        name, ip, prefix_raw = parts
        if not name or not _is_discovery_bind_ip(ip):
            continue
        try:
            prefix = int(prefix_raw)
            network = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
        except ValueError:
            continue
        interfaces.append(
            HostInterface(
                name=name.strip(),
                ip=ip.strip(),
                broadcast=str(network.broadcast_address),
            )
        )
    return interfaces


def _strip_windows_adapter_prefix(adapter_line: str) -> str:
    name = adapter_line.rstrip(":").strip()
    prefixes = (
        "以太网适配器 ",
        "无线局域网适配器 ",
        "Ethernet adapter ",
        "Wireless LAN adapter ",
    )
    for prefix in prefixes:
        if name.startswith(prefix):
            return name[len(prefix) :].strip()
    return name


def _iter_host_interfaces_windows_ipconfig() -> list[HostInterface]:
    try:
        proc = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding=_windows_console_encoding(),
            errors="replace",
            check=False,
        )
    except Exception:
        return []

    if proc.returncode != 0:
        return []

    interfaces: list[HostInterface] = []
    current_name = ""
    current_ip = ""
    current_mask = ""

    ipv4_re = re.compile(
        r"(?:IPv4\s*地址|IPv4\s*Address)[^:]*:\s*(\d+\.\d+\.\d+\.\d+)",
        re.IGNORECASE,
    )
    mask_re = re.compile(
        r"(?:子网掩码|Subnet\s*Mask)[^:]*:\s*(\d+\.\d+\.\d+\.\d+)",
        re.IGNORECASE,
    )

    def flush() -> None:
        nonlocal current_name, current_ip, current_mask
        if not current_name or not current_ip or not _is_discovery_bind_ip(current_ip):
            current_ip = ""
            current_mask = ""
            return
        broadcast = _broadcast_from_ip_mask(current_ip, current_mask or "255.255.255.0")
        if broadcast:
            interfaces.append(
                HostInterface(
                    name=current_name,
                    ip=current_ip,
                    broadcast=broadcast,
                )
            )
        current_ip = ""
        current_mask = ""

    for line in proc.stdout.splitlines():
        stripped = line.rstrip()
        if stripped and not stripped.startswith((" ", "\t")) and stripped.endswith(":"):
            flush()
            current_name = _strip_windows_adapter_prefix(stripped)
            continue
        ip_match = ipv4_re.search(line)
        if ip_match:
            current_ip = ip_match.group(1)
            continue
        mask_match = mask_re.search(line)
        if mask_match:
            current_mask = mask_match.group(1)

    flush()
    return interfaces


def _iter_host_interfaces_windows() -> list[HostInterface]:
    interfaces = _iter_host_interfaces_windows_powershell()
    if interfaces:
        return interfaces
    return _iter_host_interfaces_windows_ipconfig()


def _discovery_targets() -> list[tuple[str | None, str, str]]:
    """Return (bind_ip, destination_ip, interface_name) tuples."""
    targets: list[tuple[str | None, str, str]] = []
    seen: set[tuple[str | None, str]] = set()

    for host_if in _iter_host_interfaces():
        if not _is_discovery_bind_ip(host_if.ip):
            continue
        key = (host_if.ip, host_if.broadcast)
        if key in seen:
            continue
        seen.add(key)
        targets.append((host_if.ip, host_if.broadcast, host_if.name))

    if not any(dest == "255.255.255.255" for _, dest, _ in targets):
        targets.append((None, "255.255.255.255", ""))
    return targets


def discover_gige_devices(timeout_s: float = DEFAULT_DISCOVERY_TIMEOUT_S) -> list[dict[str, Any]]:
    packet = build_discovery_command()
    devices_by_mac: dict[str, dict[str, Any]] = {}
    targets = _discovery_targets()
    per_socket_timeout = max(timeout_s / max(len(targets), 1), 0.2)

    for bind_ip, destination, interface_name in targets:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if bind_ip:
                try:
                    sock.bind((bind_ip, 0))
                except OSError:
                    continue
            else:
                sock.bind(("", 0))
            sock.settimeout(per_socket_timeout)
            sock.sendto(packet, (destination, GVCP_PORT))

            while True:
                try:
                    data, _addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                parsed = parse_discovery_ack(data)
                if not parsed:
                    continue
                mac = parsed["mac_address"]
                if mac in devices_by_mac:
                    continue
                devices_by_mac[mac] = _gvcp_device_to_dict(parsed, interface_name)
        finally:
            sock.close()

    return sorted(
        devices_by_mac.values(),
        key=lambda item: (item.get("interface_name", ""), item.get("ip_address", "")),
    )


def _gvcp_device_to_dict(parsed: dict[str, Any], interface_name: str) -> dict[str, Any]:
    serial_number = parsed.get("serial_number", "")
    ip_address = parsed.get("ip_address", "")
    mac_address = parsed.get("mac_address", "")
    return {
        "device_id": "",
        "camera_name": parsed.get("camera_name", ""),
        "serial_number": serial_number,
        "vendor_name": parsed.get("vendor_name", ""),
        "model_name": parsed.get("model_name", ""),
        "manufacture_info": parsed.get("manufacture_info", ""),
        "device_version": parsed.get("device_version", ""),
        "interface_name": interface_name,
        "device_type": 1,
        "interface_type": 1,
        "ip_address": ip_address,
        "subnet_mask": parsed.get("subnet_mask", ""),
        "gateway": parsed.get("gateway", ""),
        "mac_address": mac_address,
        "discovery": "gvcp",
    }
