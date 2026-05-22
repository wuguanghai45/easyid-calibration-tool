import logging
import os
import random
import socket
import struct
import sys
import threading
import time
from enum import Enum


def _use_color():
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        return bool(
            os.environ.get("WT_SESSION")
            or os.environ.get("ANSICON")
            or os.environ.get("TERM") == "xterm"
        )
    return True


def setup_logger():
    class ColorFormatter(logging.Formatter):
        COLORS = {
            "DEBUG": "\033[94m",
            "INFO": "\033[92m",
            "WARNING": "\033[93m",
            "ERROR": "\033[91m",
            "CRITICAL": "\033[91m",
        }
        RESET = "\033[0m"

        def format(self, record):
            color = self.COLORS.get(record.levelname, self.RESET)
            msg = super().format(record)
            return f"{color}{msg}{self.RESET}"

    handler = logging.StreamHandler()
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    formatter = (
        ColorFormatter(fmt) if _use_color() else logging.Formatter(fmt)
    )
    handler.setFormatter(formatter)
    logger = logging.getLogger("camera")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.addHandler(handler)
    return logger


logger = setup_logger()

target_ip = "192.168.40.200"
local_ip = "192.168.40.12"
target_port = 3956
source_port = random.randint(60000, 65535)

_gvcp_sock = None
_gvcp_lock = threading.Lock()

GVCP_READREG_CMD = 0x0080
GVCP_WRITEREG_CMD = 0x0082

STREAM_PORT = 60088
AGV_PAYLOAD_OFFSET = 1300
AGV_STATUS_COMPLETE = 1


class CameraRegister(Enum):
    ACQUISITION_START = 0x00013110
    GEV_CCP_REG = 0x00000A00
    SCALE_ENABLE = 0x4E05C670
    NO_READ_SCALE = 0x4E05D844
    PARTIAL_READ_SCALE = 0x4E05D848
    COMPLETE_READ_SCALE = 0x4E05D84C


def send_and_receive_on_60088():
    """Listen on STREAM_PORT for AGV correction data from the camera."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((local_ip, STREAM_PORT))
    sock.settimeout(5.0)
    logger.info(f"Stream listener ready on {local_ip}:{STREAM_PORT}")

    current_block_id = None
    total_packets = 0
    complete_count = 0
    last_status_log = time.monotonic()
    STATUS_INTERVAL = 10.0

    try:
        while True:
            try:
                recv_data, addr = sock.recvfrom(65535)
            except socket.timeout:
                now = time.monotonic()
                if now - last_status_log >= STATUS_INTERVAL:
                    logger.info(
                        f"Waiting for AGV data on {local_ip}:{STREAM_PORT} "
                        f"(packets={total_packets}, complete={complete_count})"
                    )
                    last_status_log = now
                continue

            total_packets += 1
            if total_packets == 1:
                logger.info(f"First stream packet from {addr[0]}:{addr[1]}")

            block_id = struct.unpack(">H", recv_data[2:4])[0]
            packet_id = int.from_bytes(recv_data[5:8], byteorder="big")

            if packet_id != 1:
                continue
            if current_block_id is not None and block_id == current_block_id:
                continue

            current_block_id = block_id
            start_index = AGV_PAYLOAD_OFFSET

            if len(recv_data) < start_index + 4:
                continue

            agv_status = int.from_bytes(
                recv_data[start_index : start_index + 4],
                byteorder="little",
                signed=True,
            )
            if agv_status != AGV_STATUS_COMPLETE:
                continue

            complete_count += 1

            # Skip agv_time (4) and agv_error_code (4)
            start_index += 12
            x_offset = int.from_bytes(
                recv_data[start_index : start_index + 4],
                byteorder="little",
                signed=True,
            )
            start_index += 4
            y_offset = int.from_bytes(
                recv_data[start_index : start_index + 4],
                byteorder="little",
                signed=True,
            )
            start_index += 4
            theta = int.from_bytes(
                recv_data[start_index : start_index + 4],
                byteorder="little",
                signed=True,
            )
            start_index += 4

            str_len_index = start_index + 64
            string_length = int.from_bytes(
                recv_data[str_len_index : str_len_index + 4],
                byteorder="little",
            )
            string_value = ""
            if string_length > 0:
                string_value = recv_data[
                    start_index : start_index + string_length
                ].decode("utf-8", errors="ignore")

            logger.info(
                f"x offset: {x_offset}, y offset: {y_offset}, "
                f"theta: {theta}, code: {string_value}"
            )
    except KeyboardInterrupt:
        logger.warning("Stopped receiving.")
    finally:
        sock.close()


def ip_to_int(ip_address):
    hex_representation = "".join(
        f"{int(octet):02x}" for octet in ip_address.split(".")
    )
    return int(hex_representation, 16)


def heartbeat_loop():
    fail_streak = 0
    while True:
        packet = create_packet_dynamic(
            {CameraRegister.GEV_CCP_REG.value: None}, GVCP_READREG_CMD
        )
        ok = send_packet(packet, target_ip, target_port, source_port)
        if ok:
            fail_streak = 0
        else:
            fail_streak += 1
            if fail_streak == 1 or fail_streak % 10 == 0:
                logger.warning(
                    f"Camera heartbeat failed ({fail_streak}x), "
                    f"check {target_ip}:{target_port} and network"
                )
        time.sleep(1)


def set_zero_size_image_output():
    registers = (
        CameraRegister.SCALE_ENABLE,
        CameraRegister.NO_READ_SCALE,
        CameraRegister.PARTIAL_READ_SCALE,
        CameraRegister.COMPLETE_READ_SCALE,
    )
    values = (1, 10, 10, 10)
    ret = True
    for reg, value in zip(registers, values):
        packet = create_packet_dynamic({reg.value: value})
        ret &= send_packet(packet, target_ip, target_port, source_port)
    return ret


def start_acquisition():
    packet = create_packet_dynamic({CameraRegister.ACQUISITION_START.value: 1})
    return send_packet(packet, target_ip, target_port, source_port)


def disconnect():
    packet = create_packet_dynamic({0x00000D00: 0x00000000})
    send_packet(packet, target_ip, target_port, source_port)
    packet = create_packet_dynamic({0x00000A00: 0x00000000})
    send_packet(packet, target_ip, target_port, source_port)


def connect():
    logger.info(
        f"Connecting camera {target_ip}:{target_port} "
        f"(local {local_ip}, GVCP port {source_port}, stream {STREAM_PORT})"
    )
    ok = True
    control_switchover_key = 0x0000
    control_switchover_enable = 0
    control_access = 1
    exclusive_access = 0
    control_byte = (
        (control_switchover_enable << 2)
        | (control_access << 1)
        | exclusive_access
    )

    binary_data = struct.pack(
        "!HBBBB",
        control_switchover_key,
        0x00,
        0x00,
        0x00,
        control_byte,
    )
    value = int.from_bytes(binary_data, byteorder="big")
    packet = create_packet_dynamic({0x00000A00: value})
    ok &= send_packet(packet, target_ip, target_port, source_port)

    for address, reg_value in (
        (0x00000938, 3000),
        (0x00000B18, 3),
        (0x00000B14, 300),
        (0x00000D18, ip_to_int(local_ip)),
        (0x00000D00, STREAM_PORT),
        (0x00000D04, 0xC00005DC),
        (0x00000D04, 0x400005A4),
    ):
        packet = create_packet_dynamic({address: reg_value})
        if not send_packet(packet, target_ip, target_port, source_port):
            logger.error(f"Failed to write register 0x{address:08X}")
            ok = False

    ip = ip_to_int(local_ip)
    packet = create_packet_dynamic(
        {
            0x00000B10: ip,
            0x00000B00: source_port - 1,
        },
    )
    for _ in range(3):
        ok &= send_packet(packet, target_ip, target_port, source_port)

    if ok:
        logger.info("Camera connected and stream destination configured.")
    else:
        logger.error(
            "Camera connect incomplete — verify IP and that no other app "
            "controls the camera."
        )
    return ok


def create_packet_dynamic(data_map=None, command_type=GVCP_WRITEREG_CMD):
    """Build GVCP packet; value=None sends address only (read register)."""
    message_key_code = 0x42
    flags = 0x01

    if data_map is None:
        data_map = {}

    payload_length = sum(
        4 if value is None else 8 for value in data_map.values()
    )
    request_id = random.randint(1, 0xFFFF)

    header = struct.pack(
        "!BBHHH",
        message_key_code,
        flags,
        command_type,
        payload_length,
        request_id,
    )

    payload = b""
    for address, value in data_map.items():
        if not isinstance(address, int):
            raise ValueError("address must be int")
        if value is None:
            payload += struct.pack("!L", address)
        else:
            if not isinstance(value, int):
                raise ValueError("value must be int or None")
            payload += struct.pack("!LL", address, value)

    return header + payload


def _get_gvcp_socket(bind_port):
    """Reuse one UDP socket for all GVCP traffic (avoids WinError 10048)."""
    global _gvcp_sock
    if _gvcp_sock is not None:
        return _gvcp_sock

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", bind_port))
    _gvcp_sock = sock
    return _gvcp_sock


def close_gvcp_socket():
    global _gvcp_sock
    if _gvcp_sock is not None:
        _gvcp_sock.close()
        _gvcp_sock = None


def send_packet(packet, target_ip, target_port, source_port=None, timeout=1):
    with _gvcp_lock:
        try:
            if source_port is not None:
                sock = _get_gvcp_socket(source_port)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(packet, (target_ip, target_port))
            response, addr = sock.recvfrom(4096)
            logger.debug(f"Received response from {addr}: {response.hex()}")

            if len(response) < 2:
                logger.error("Response too short to determine success.")
                return False

            status = struct.unpack(">H", response[0:2])[0]
            ack_knowledge = struct.unpack(">H", response[2:4])[0]
            if status != 0:
                logger.error(
                    f"Command failed with status: {status}, "
                    f"ack_knowledge: {ack_knowledge}"
                )
                return False

            if ack_knowledge in (
                GVCP_READREG_CMD + 0x0001,
                GVCP_WRITEREG_CMD + 0x0001,
            ):
                return True

            logger.error(f"Unexpected ack_knowledge: {ack_knowledge}")
            return False
        except socket.timeout:
            logger.error("No response received: Timeout occurred.")
            return False
        except Exception as e:
            logger.error(f"Error: {e}")
            return False


if __name__ == "__main__":
    try:
        if not connect():
            raise SystemExit(1)

        logger.info("Waiting 2s for camera to apply settings...")
        time.sleep(2)

        if not set_zero_size_image_output():
            logger.error("Failed to set zero size image output.")
            raise SystemExit(1)
        logger.info("Zero-size image output configured.")

        threading.Thread(target=send_and_receive_on_60088, daemon=True).start()
        time.sleep(0.2)

        if not start_acquisition():
            logger.error("Failed to start acquisition.")
            raise SystemExit(1)
        logger.info("Acquisition started.")

        threading.Thread(target=heartbeat_loop, daemon=True).start()
        logger.info(
            "Running. Place a code in view; Ctrl+C to stop. "
            "Status updates every 10s if no AGV result yet."
        )

        while True:
            if not set_zero_size_image_output():
                logger.error("Failed to refresh zero size image output.")
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    finally:
        disconnect()
        close_gvcp_socket()
