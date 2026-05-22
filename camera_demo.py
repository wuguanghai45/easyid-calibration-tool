import math
import re
import socket
import time

# Huaray AGV result: (x_offset;y_offset;theta;barcode)
_SCAN_PATTERN = re.compile(r"\(([^)]+)\)")


def radians_to_huaray_theta(theta_rad: float) -> int:
    """
    Convert radians to Huaray theta: clockwise [0, 3599], 0.1 deg per unit.
    Matches: (int32_t)(theta / M_PI * 1800 + 1800) % 3600
    """
    return int(theta_rad / math.pi * 1800 + 1800) % 3600


def huaray_theta_to_degrees(theta: int) -> float:
    """Camera theta unit -> degrees (3600 units = 360 deg)."""
    return (int(theta) % 3600) / 10.0


def parse_scan_payload(text: str) -> list[dict[str, str | int]]:
    """Parse one or more (x;y;theta;code) messages from TCP text."""
    results: list[dict[str, str | int]] = []
    for match in _SCAN_PATTERN.finditer(text):
        parts = match.group(1).split(";")
        if len(parts) < 4:
            continue
        try:
            results.append(
                {
                    "x_offset": int(parts[0]),
                    "y_offset": int(parts[1]),
                    "theta": int(parts[2]) % 3600,
                    "code": ";".join(parts[3:]),
                }
            )
        except ValueError:
            continue
    return results


def print_scan_result(item: dict[str, str | int]) -> None:
    theta = int(item["theta"])
    print(
        f"[扫码结果] x偏移量: {item['x_offset']}, "
        f"y偏移量: {item['y_offset']}, "
        f"角度: {theta} (华睿[0,3599], 顺时针, {huaray_theta_to_degrees(theta):.1f}°), "
        f"条码: {item['code']}"
    )


def connect_to_camera(camera_ip, camera_port):
    """Connect to Huaray camera TCP server and print AGV scan results."""
    print(f"[正在连接] 尝试连接相机 {camera_ip}:{camera_port}...")

    while True:
        client = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(5.0)
            client.connect((camera_ip, camera_port))
            client.settimeout(None)
            print("[连接成功] 已成功连接到华睿相机！")

            while True:
                data = client.recv(1024)
                if not data:
                    print("[连接断开] 相机主动关闭了连接。")
                    break

                text = data.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue

                parsed = parse_scan_payload(text)
                if parsed:
                    for item in parsed:
                        print_scan_result(item)
                else:
                    print(f"[原始数据]: {text}")

        except (socket.timeout, OSError) as e:
            print(f"[连接失败/掉线] 原因: {e}。 5秒后尝试重连...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n[程序退出] 用户终止了程序。")
            break
        finally:
            if client is not None:
                client.close()


if __name__ == "__main__":
    CAMERA_IP = "192.168.40.200"
    CAMERA_PORT = 3000

    connect_to_camera(CAMERA_IP, CAMERA_PORT)
