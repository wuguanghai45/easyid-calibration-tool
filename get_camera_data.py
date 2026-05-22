"""CLI entry for Huaray TCP scan results (delegates to scanner.tcp_scan)."""

from __future__ import annotations

from scanner.tcp_scan import TcpScanClient, huaray_theta_to_degrees


def print_scan_result(item: dict) -> None:
    theta = int(item["theta"])
    print(
        f"[扫码结果] x偏移量: {item['x_offset']}, "
        f"y偏移量: {item['y_offset']}, "
        f"角度: {theta} ({huaray_theta_to_degrees(theta):.1f}°), "
        f"条码: {item['code']}"
    )


def connect_to_camera(camera_ip: str, camera_port: int) -> None:
    """Connect to Huaray camera TCP server and print AGV scan results."""
    print(f"[正在连接] 尝试连接相机 {camera_ip}:{camera_port}...")

    client = TcpScanClient(host=camera_ip, port=camera_port)
    client.subscribe(lambda item: print_scan_result(item))
    client.start()

    try:
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[程序退出] 用户终止了程序。")
    finally:
        client.stop()


if __name__ == "__main__":
    CAMERA_IP = "192.168.40.200"
    CAMERA_PORT = 3000
    connect_to_camera(CAMERA_IP, CAMERA_PORT)
