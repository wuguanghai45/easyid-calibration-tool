import socket
import time

def connect_to_camera(camera_ip, camera_port):
    """
    主动连接作为 TCP Server 的华睿相机
    """
    print(f"[正在连接] 尝试连接相机 {camera_ip}:{camera_port}...")
    
    while True:
        try:
            # 创建 socket 并尝试连接
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(5.0) # 设置连接超时
            client.connect((camera_ip, camera_port))
            client.settimeout(None) # 取消超时限制，恢复阻塞接收
            print("[连接成功] 已成功连接到华睿相机！")
            
            while True:
                # 接收扫码结果
                data = client.recv(1024)
                if not data:
                    print("[连接断开] 相机主动关闭了连接。")
                    break
                
                # 解析条码
                barcode = data.decode('utf-8', errors='ignore').strip()
                if barcode:
                    print(f"[扫码数据]: {barcode}")
                    
        except (socket.timeout, socket.error) as e:
            print(f"[连接失败/掉线] 原因: {e}。 5秒后尝试重连...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n[程序退出] 用户终止了程序。")
            break
        finally:
            client.close()

if __name__ == '__main__':
    # 替换为你华睿相机的实际 IP 和在软件中配置的监听端口
    CAMERA_IP = '192.168.40.200'
    CAMERA_PORT = 3000
    
    connect_to_camera(CAMERA_IP, CAMERA_PORT)