import socket
import struct
import random
import time
from enum import Enum
import threading
import datetime

import logging


def setup_logger():
    class ColorFormatter(logging.Formatter):
        COLORS = {
            "DEBUG": "\033[94m",  # 蓝色
            "INFO": "\033[92m",  # 绿色
            "WARNING": "\033[93m",  # 黄色
            "ERROR": "\033[91m",  # 红色
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


target_ip = "192.168.40.200"  # 目标设备的 IP 地址
local_ip = "192.168.40.12"  # 本机IP

target_port = 3956  # 目标设备的端口
source_port = random.randint(60000, 65535)  # 设置源端口（可以根据需要更改）

GVCP_READREG_CMD = 0x0080
GVCP_WRITEREG_CMD = 0x0082


class CameraRegister(Enum):
    EXPOSURE_TIME = 0x00013020
    GAIN_RAW = 0x4E0580A0
    BRIGHTNESS = 0x4E05C9A0
    ACQUISITION_START = 0x00013110
    ACQUISITION_STOP = 0x00013120
    CHUNK_MODE_ACTIVE = 0x0001B000
    COMM_MODE = 0x4E05D880
    TRANSFER_WORK_MODE = 0x4E05C73C
    GEV_CCP_REG = 0x00000A00
    SCALE_ENABLE = 0x4E05C670
    NO_READ_SCALE = 0x4E05D844
    PARTIAL_READ_SCALE = 0x4E05D848
    COMPLETE_READ_SCALE = 0x4E05D84C


def send_and_receive_on_60088():
    """
    在60088端口发送自定义UDP包并循环接收数据
    """
    listen_ip = local_ip
    listen_port = 60088
    # target_ip = "169.254.0.10"
    # target_port = 20202
    # data = bytes([0x30])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((listen_ip, listen_port))
    current_block_id = None

    AGV_STATUS = {0: "NA", 1: "Complete", 2: "NoRead", 3: "Partial", 4: "Fail"}

    AGV_ERROR_CODE = {
        0: "NoErr",
        1: "ErrSysTime",
        2: "ErrRepeated",
        3: "ErrLocation",
        4: "ErrValue",
    }
    try:
        while True:
            start_index = 1300
            recv_data, addr = sock.recvfrom(65535)
            # print(f"Received {len(recv_data)} bytes from {addr}")
            # print(recv_data.hex())
            status = struct.unpack(">H", recv_data[0:2])[0]
            block_id = struct.unpack(">H", recv_data[2:4])[0]
            format = recv_data[4]  # 1字节
            packet_id = int.from_bytes(recv_data[5:8], byteorder="big")  # 3字节

            # print("Status:", status)
            # print("Block ID:", block_id)
            # print("Format:", format)
            # print("packet_id:", packet_id)

            if packet_id == 1:
                if current_block_id is None or block_id != current_block_id:
                    # print(f"Data : {recv_data.hex()}")
                    current_block_id = block_id

                    agv_status = int.from_bytes(
                        recv_data[start_index: start_index + 4],
                        byteorder="little",
                        signed=True,
                    )

                    logger.debug(
                        f"AGV Status: {AGV_STATUS.get(agv_status, 'Unknown')} ({agv_status})"
                    )
                    if agv_status != 1:
                        continue

                    start_index += 4
                    agv_time = int.from_bytes(
                        recv_data[start_index: start_index + 4],
                        byteorder="little",
                        signed=True,
                    )

                    start_index += 4
                    agv_error_code = int.from_bytes(
                        recv_data[start_index: start_index + 4],
                        byteorder="little",
                        signed=True,
                    )

                    # print(
                    #     f"AGV Error Code: {AGV_ERROR_CODE.get(agv_error_code, 'Unknown')} ({agv_error_code})"
                    # )

                    start_index += 4
                    x_offset = int.from_bytes(
                        recv_data[start_index: start_index + 4],
                        byteorder="little",
                        signed=True,
                    )
                    start_index += 4
                    y_offset = int.from_bytes(
                        recv_data[start_index: start_index + 4],
                        byteorder="little",
                        signed=True,
                    )
                    start_index += 4
                    theta = int.from_bytes(
                        recv_data[start_index: start_index + 4],
                        byteorder="little",
                        signed=True,
                    )

                    # print(f"x offset: {x_offset}, y offset: {y_offset}, theta: {theta}")

                    start_index += 4

                    str_len_index = start_index + 64
                    string_length = int.from_bytes(
                        recv_data[str_len_index: str_len_index +
                                  4], byteorder="little"
                    )
                    if string_length > 0:
                        string_value = recv_data[
                            start_index: start_index + string_length
                        ].decode("utf-8", errors="ignore")

                    # print(f"String length: {string_length}")

                    logger.info(
                        f"x offset: {x_offset}, y offset: {y_offset}, theta: {theta}, code: {string_value}"
                    )

    except KeyboardInterrupt:
        logger.warning("Stopped receiving.")
    finally:
        sock.close()


def ip_to_int(ip_address):
    hex_representation = "".join(
        [f"{int(octet):02x}" for octet in ip_address.split(".")]
    )
    return int(hex_representation, 16)


def heartbeat_loop():
    while True:
        packet = create_packet_dynamic(
            {CameraRegister.GEV_CCP_REG.value: None}, GVCP_READREG_CMD
        )
        send_packet(packet, target_ip, target_port, source_port)
        time.sleep(1)


def float_to_ieee754(value):
    return struct.unpack("!I", struct.pack("!f", value))[0]


def set_zero_size_image_output():
    packet = create_packet_dynamic({CameraRegister.SCALE_ENABLE.value: 1})
    ret = send_packet(packet, target_ip, target_port, source_port)
    packet = create_packet_dynamic({CameraRegister.NO_READ_SCALE.value: 10})
    ret &= send_packet(packet, target_ip, target_port, source_port)
    packet = create_packet_dynamic(
        {CameraRegister.PARTIAL_READ_SCALE.value: 10})
    ret &= send_packet(packet, target_ip, target_port, source_port)
    packet = create_packet_dynamic(
        {CameraRegister.COMPLETE_READ_SCALE.value: 10})
    ret &= send_packet(packet, target_ip, target_port, source_port)
    return ret


def set_transfer_work_mode(value):
    packet = create_packet_dynamic(
        {CameraRegister.TRANSFER_WORK_MODE.value: value})
    send_packet(packet, target_ip, target_port, source_port)


def set_comm_mode(value):
    packet = create_packet_dynamic({CameraRegister.COMM_MODE.value: value})
    send_packet(packet, target_ip, target_port, source_port)


def set_exposure_time(value):
    value = max(20, min(value, 1690))
    exposure_time = float_to_ieee754(value)
    packet = create_packet_dynamic(
        {CameraRegister.EXPOSURE_TIME: exposure_time})
    send_packet(packet, target_ip, target_port, source_port)


def set_gain_raw(value):
    value = max(1, min(value, 60))
    gain_raw = float_to_ieee754(value)
    packet = create_packet_dynamic({CameraRegister.GAIN_RAW: gain_raw})
    send_packet(packet, target_ip, target_port, source_port)


def set_brightness(value):
    brightness = int(max(10, min(value, 100)))
    packet = create_packet_dynamic(
        {CameraRegister.BRIGHTNESS.value: brightness})
    send_packet(packet, target_ip, target_port, source_port)


def start_acquisition():
    packet = create_packet_dynamic({CameraRegister.ACQUISITION_START.value: 1})
    send_packet(packet, target_ip, target_port, source_port)


def start_chunk_mode():
    packet = create_packet_dynamic({CameraRegister.CHUNK_MODE_ACTIVE.value: 1})
    send_packet(packet, target_ip, target_port, source_port)


def disconnect():
    packet = create_packet_dynamic({0x00000D00: 0x00000000})
    send_packet(packet, target_ip, target_port, source_port)
    packet = create_packet_dynamic({0x00000A00: 0x00000000})
    send_packet(packet, target_ip, target_port, source_port)


def connect():
    control_switchover_key = 0x0000  # 16 bits
    control_switchover_enable = 0  # 1 bit
    control_access = 1  # 1 bit
    exclusive_access = 0  # 1 bit

    # 打包到 32 位寄存器 (4 bytes)
    # 16 bits for Control Switchover Key, then 1 bit for each flag, padded to align
    control_byte = (
        (control_switchover_enable << 2) | (
            control_access << 1) | exclusive_access
    )

    binary_data = struct.pack(
        "!HBBBB",  # Correct format for a 16-bit request_id
        control_switchover_key,  # 2 byte
        0x00,  # 1 byte
        0x00,  # 1 bytes
        0x00,  # 1 bytes
        control_byte,  # 1 bytes
    )

    # print(f"binary_data (hex): {binary_data.hex()}")
    value = int.from_bytes(binary_data, byteorder="big")
    # print(f"value (hex): {hex(value)}")
    packet = create_packet_dynamic({0x00000A00: value})
    send_packet(packet, target_ip, target_port, source_port)

    # Heartbeat Timeout (in ms): 3000
    packet = create_packet_dynamic({0x00000938: 3000})
    send_packet(packet, target_ip, target_port, source_port)

    # Retry Count: 3
    packet = create_packet_dynamic({0x00000B18: 3})
    send_packet(packet, target_ip, target_port, source_port)

    # Transmission Timeout (in ms): 300
    packet = create_packet_dynamic({0x00000B14: 300})
    send_packet(packet, target_ip, target_port, source_port)

    # Destination Address: 169.254.159.26
    packet = create_packet_dynamic({0x00000D18: ip_to_int(local_ip)})
    send_packet(packet, target_ip, target_port, source_port)

    # Host Port: 60088
    packet = create_packet_dynamic({0x00000D00: 60088})
    send_packet(packet, target_ip, target_port, source_port)

    # Packet Size: 1500
    packet = create_packet_dynamic({0x00000D04: 0xC00005DC})
    send_packet(packet, target_ip, target_port, source_port)

    # Packet Size: 1444
    packet = create_packet_dynamic({0x00000D04: 0x400005A4})
    send_packet(packet, target_ip, target_port, source_port)

    # packet = create_packet_dynamic({0xE0000000: 0x00010001})
    # send_packet(packet, target_ip, target_port, source_port)

    # Host Port
    ip = ip_to_int(local_ip)
    packet = create_packet_dynamic(
        {
            0x00000B10: ip,  # Address: 0xAABBCCDD, Value: 12345
            0x00000B00: source_port - 1,  # Address: 0x11223344, Value: 67890
        },
    )
    send_packet(packet, target_ip, target_port, source_port)
    send_packet(packet, target_ip, target_port, source_port)
    send_packet(packet, target_ip, target_port, source_port)


def create_packet_dynamic(data_map=None, command_type=GVCP_WRITEREG_CMD, debug=False):
    """
    构造 WRITEREG_CMD 数据包，支持 value 为 None（只发送地址，不发送 value）
    """
    message_key_code = 0x42
    flags = 0x01

    if data_map is None:
        data_map = {}

    # 计算 payload 长度
    payload_length = 0
    for address, value in data_map.items():
        if value is None:
            payload_length += 4  # 只发地址
        else:
            payload_length += 8  # 地址+值

    request_id = random.randint(1, 0xFFFF)

    # 打包头部
    header = struct.pack(
        "!BBHHH",
        message_key_code,
        flags,
        command_type,
        payload_length,
        request_id,
    )

    # 打包 payload
    payload = b""
    for address, value in data_map.items():
        if not isinstance(address, int):
            raise ValueError("地址必须是整数")
        if value is None:
            payload += struct.pack("!L", address)
        else:
            if not isinstance(value, int):
                raise ValueError("值必须是整数或 None")
            payload += struct.pack("!LL", address, value)

    packet = header + payload

    if debug:
        logger.debug(f"Request ID: {hex(request_id)}")
        logger.debug(f"Payload Length: {payload_length} bytes")
        logger.debug("Arguments:")
        for address, value in data_map.items():
            logger.debug(f"  Address: {hex(address)}, Value: {value}")
        logger.debug(f"Packet (hex): {packet.hex()}")

    return packet


def send_packet(packet, target_ip, target_port, source_port=None, timeout=1):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 如果需要指定源端口
        if source_port is not None:
            sock.bind(("", source_port))  # 绑定到指定的源端口

        # 设置超时时间
        sock.settimeout(timeout)

        # 发送数据包
        sock.sendto(packet, (target_ip, target_port))
        # print(
        #     f"Packet sent successfully from source port {source_port if source_port else 'random'}!"
        # )

        # 等待接收回复
        response, addr = sock.recvfrom(4096)  # 最大接收缓冲区大小为 4096 字节
        logger.debug(f"Received response from {addr}: {response.hex()}")

        # 判断最后两个字节
        if len(response) >= 2:
            status = struct.unpack(">H", response[0:2])[0]
            ack_knowledge = struct.unpack(">H", response[2:4])[0]
            if status == 0:
                if ack_knowledge == GVCP_READREG_CMD + 0x0001:
                    logger.debug("Read operation acknowledged.")
                elif ack_knowledge == GVCP_WRITEREG_CMD + 0x0001:
                    logger.debug("Write operation acknowledged.")
                else:
                    logger.error(f"Unexpected ack_knowledge: {ack_knowledge}")
                    return False
                return True
            else:
                logger.error(
                    f"Command failed with status: {status}, ack_knowledge: {ack_knowledge}"
                )
                return False
        else:
            logger.error("Response too short to determine success.")
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

    connect()

    # value = random.uniform(20, 1690)
    # print(f"exposure_time: {value}")
    # set_exposure_time(value)

    # value = random.uniform(1, 60)
    # print(f"gain_raw: {value}")
    # set_gain_raw(value)

    # value = int(random.uniform(10, 100))
    # print(f"brightness: {value}")
    # set_brightness(value)

    time.sleep(2)

    if not set_zero_size_image_output():
        logger.error("Failed to set zero size image output.")
        exit(1)

    receiver_thread = threading.Thread(
        target=send_and_receive_on_60088, daemon=True)
    receiver_thread.start()

    start_acquisition()

    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    while True:

        if not set_zero_size_image_output():
            logger.error("Failed to set zero size image output.")
        time.sleep(2)

    disconnect()
    time.sleep(0.2)
