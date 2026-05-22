import logging
import random
import socket
import struct
import threading
import time
from enum import Enum


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
    formatter = ColorFormatter("%(asctime)s [%(levelname)s] %(message)s")
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
    sock.bind((local_ip, STREAM_PORT))
    current_block_id = None

    try:
        while True:
            recv_data, _ = sock.recvfrom(65535)
            block_id = struct.unpack(">H", recv_data[2:4])[0]
            packet_id = int.from_bytes(recv_data[5:8], byteorder="big")

            if packet_id != 1:
                continue
            if current_block_id is not None and block_id == current_block_id:
                continue

            current_block_id = block_id
            start_index = AGV_PAYLOAD_OFFSET

            agv_status = int.from_bytes(
                recv_data[start_index : start_index + 4],
                byteorder="little",
                signed=True,
            )
            if agv_status != AGV_STATUS_COMPLETE:
                continue

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
    while True:
        packet = create_packet_dynamic(
            {CameraRegister.GEV_CCP_REG.value: None}, GVCP_READREG_CMD
        )
        send_packet(packet, target_ip, target_port, source_port)
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
    send_packet(packet, target_ip, target_port, source_port)


def disconnect():
    packet = create_packet_dynamic({0x00000D00: 0x00000000})
    send_packet(packet, target_ip, target_port, source_port)
    packet = create_packet_dynamic({0x00000A00: 0x00000000})
    send_packet(packet, target_ip, target_port, source_port)


def connect():
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
    send_packet(packet, target_ip, target_port, source_port)

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
        send_packet(packet, target_ip, target_port, source_port)

    ip = ip_to_int(local_ip)
    packet = create_packet_dynamic(
        {
            0x00000B10: ip,
            0x00000B00: source_port - 1,
        },
    )
    for _ in range(3):
        send_packet(packet, target_ip, target_port, source_port)


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


def send_packet(packet, target_ip, target_port, source_port=None, timeout=1):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if source_port is not None:
            sock.bind(("", source_port))
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
    finally:
        sock.close()


if __name__ == "__main__":
    try:
        connect()
        time.sleep(2)

        if not set_zero_size_image_output():
            logger.error("Failed to set zero size image output.")
            raise SystemExit(1)

        threading.Thread(target=send_and_receive_on_60088, daemon=True).start()
        start_acquisition()
        threading.Thread(target=heartbeat_loop, daemon=True).start()

        while True:
            if not set_zero_size_image_output():
                logger.error("Failed to set zero size image output.")
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    finally:
        disconnect()
