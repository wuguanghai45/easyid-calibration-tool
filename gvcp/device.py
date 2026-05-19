"""High-level GVCP device session wrapper."""

from __future__ import annotations

from dataclasses import dataclass

from .transport import GvcpClient

# GigE Vision bootstrap register addresses (common).
REG_GEV_VERSION = 0x0000
REG_GEV_XML_URL_0 = 0x0200
REG_GEV_XML_URL_1 = 0x0400
REG_GEV_SCPS_PACKET_SIZE = 0x0D04
REG_GEV_SCPD = 0x0D08
REG_GEV_SCDA0 = 0x0D18
REG_GEV_SCDA1 = 0x0D1C
REG_GEV_SCP_HOST_PORT = 0x0D00


@dataclass
class GvcpDevice:
    device_ip: str
    bind_ip: str
    timeout_s: float = 1.0

    def __post_init__(self) -> None:
        self.client = GvcpClient(self.device_ip, self.bind_ip, timeout_s=self.timeout_s)

    def close(self) -> None:
        self.client.close()

    def read_register(self, address: int) -> int:
        return self.client.read_register(address)

    def write_register(self, address: int, value: int) -> None:
        self.client.write_register(address, value)

    def read_memory(self, address: int, size: int) -> bytes:
        return self.client.read_memory(address, size)

    def write_memory(self, address: int, data: bytes) -> None:
        self.client.write_memory(address, data)

    def read_xml_url_candidates(self) -> list[str]:
        urls: list[str] = []
        for register in (REG_GEV_XML_URL_0, REG_GEV_XML_URL_1):
            raw_value = self.read_register(register)
            if raw_value <= 0:
                continue
            # Some devices store direct memory pointer in URL register.
            data = self.read_memory(raw_value, 512)
            text = data.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
            if text:
                urls.append(text)
        return urls

    def configure_stream_destination(self, host_ip_u32: int, host_port: int, packet_size: int = 1400, scpd: int = 0) -> None:
        # These registers are common across GigE Vision devices.
        self.write_register(REG_GEV_SCPS_PACKET_SIZE, packet_size)
        self.write_register(REG_GEV_SCPD, scpd)
        self.write_register(REG_GEV_SCDA0, 0)
        self.write_register(REG_GEV_SCDA1, host_ip_u32)
        self.write_register(REG_GEV_SCP_HOST_PORT, host_port)

