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
XML_URL_BLOCK_SIZE = 512


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

    def read_memory_chunked(self, address: int, size: int, chunk_size: int = 512) -> bytes:
        if size <= 0:
            return b""
        if chunk_size <= 0:
            chunk_size = 512
        chunks: list[bytes] = []
        remaining = size
        offset = 0
        while remaining > 0:
            current = min(remaining, chunk_size)
            try:
                part = self.read_memory(address + offset, current)
            except Exception:
                if chunks:
                    break
                raise
            if len(part) == 0:
                break
            if len(part) < current:
                # Some devices cap per-read length; stop on short read to avoid endless retries.
                chunks.append(part)
                break
            chunks.append(part)
            step = len(part)
            offset += step
            remaining -= step
        return b"".join(chunks)[:size]

    def read_memory_fixed_base(self, address: int, size: int, chunk_size: int = 512) -> bytes:
        """Read memory using a fixed base address repeatedly.

        Some devices expose local XML data through a FIFO-like window where the
        address is constant and each READMEM returns the next chunk.
        """
        if size <= 0:
            return b""
        if chunk_size <= 0:
            chunk_size = 512
        chunks: list[bytes] = []
        remaining = size
        last_chunk: bytes | None = None
        while remaining > 0:
            current = min(remaining, chunk_size)
            try:
                part = self.read_memory(address, current)
            except Exception:
                break
            if not part:
                break
            if last_chunk is not None and part == last_chunk:
                break
            chunks.append(part)
            last_chunk = part
            remaining -= len(part)
        return b"".join(chunks)[:size]

    def write_memory(self, address: int, data: bytes) -> None:
        self.client.write_memory(address, data)

    def read_xml_url_candidates(self) -> list[str]:
        urls: list[str] = []
        for register in (REG_GEV_XML_URL_0, REG_GEV_XML_URL_1):
            # GigE Vision bootstrap usually stores URL text directly in register blocks.
            data = self._read_register_block(register, XML_URL_BLOCK_SIZE)
            text = data.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
            if text:
                urls.append(text)
                continue

            # Fallback: some vendor devices expose a pointer in the first register.
            raw_value = int.from_bytes(data[:4], byteorder="big", signed=False)
            if raw_value <= 0:
                continue
            try:
                mem_data = self.read_memory(raw_value, XML_URL_BLOCK_SIZE)
            except Exception:
                continue
            mem_text = mem_data.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
            if mem_text:
                urls.append(mem_text)
        return urls

    def _read_register_block(self, start_address: int, size: int) -> bytes:
        if size <= 0:
            return b""
        chunks: list[bytes] = []
        words = (size + 3) // 4
        for index in range(words):
            value = self.read_register(start_address + index * 4)
            chunks.append(int(value & 0xFFFFFFFF).to_bytes(4, byteorder="big", signed=False))
        return b"".join(chunks)[:size]

    def configure_stream_destination(self, host_ip_u32: int, host_port: int, packet_size: int = 1400, scpd: int = 0) -> None:
        # These registers are common across GigE Vision devices.
        self.write_register(REG_GEV_SCPS_PACKET_SIZE, packet_size)
        self.write_register(REG_GEV_SCPD, scpd)
        self.write_register(REG_GEV_SCDA0, 0)
        self.write_register(REG_GEV_SCDA1, host_ip_u32)
        self.write_register(REG_GEV_SCP_HOST_PORT, host_port)

