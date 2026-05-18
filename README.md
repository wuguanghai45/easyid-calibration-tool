# EasyID Scanner Calibration Tool

工厂标定数据采集工具，通过 EasyID SDK 连接扫码器，自动导出软件/硬件配置、触发一次软触发采图，并将设备信息、解码结果与图像保存到本地目录。

## 功能概述

一次完整采集会依次完成：

1. 枚举并连接指定扫码器（序列号或 IP）
2. 保存 `device_info.json`（型号、SN、IP、MAC 等）
3. 导出 `software_config.xml` 与 `hardware_config.xml`
4. 软触发采集一帧，保存图像与 `scan_result.json`（解码状态、条码内容、坐标等）

可选：`--dump-features` 导出设备 GenICam 特征树候选节点，用于调试不同机型的特征名差异。

## 环境要求

| 项目 | 说明 |
|------|------|
| 操作系统 | **Windows**（推荐）；Linux 需自行配置 `EasyID.py` 中的 `libEasyID.so` 路径 |
| Python | 3.10+（建议 3.10 或 3.11） |
| EasyID SDK | 已安装官方 EasyID 运行时，且 `EasyID.dll` 可被加载 |
| 网络 | 扫码器与 PC 在同一网段（使用 `--ip` 时） |

### Windows：配置 SDK 环境变量

根据 Python 位数设置其一（路径为 EasyID 安装目录，目录下应包含 `EasyID.dll`）：

- 64 位 Python：`EASYID_RUNENV_64`
- 32 位 Python：`EASYID_RUNENV_32`

PowerShell 示例：

```powershell
[System.Environment]::SetEnvironmentVariable("EASYID_RUNENV_64", "C:\Program Files\EasyID", "User")
```

修改环境变量后需**重新打开**终端再运行脚本。

## 安装依赖

在项目根目录执行：

```bash
pip install -r requirements.txt
```

`Pillow` 用于将 Mono8 原始图像保存为 PNG；若未安装，Mono8 会保存为 `.raw`，JPEG 帧仍正常保存为 `.jpg`。

## 使用方法

### 基本命令

通过**序列号**连接：

```bash
python read_scanner_calibration.py --sn <扫码器序列号>
```

通过 **IP 地址**连接：

```bash
python read_scanner_calibration.py --ip 192.168.1.100
```

`--sn` 与 `--ip` 二选一，必填其一。

### 常用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--output` | `./calibration_out` | 输出根目录；每次运行在其下新建带时间戳的子目录 |
| `--timeout-ms` | `2000` | 取帧超时（毫秒） |
| `--buffer-count` | `3` | SDK 采集缓冲区数量 |
| `--no-clear-buffer` | 关闭 | 采图前不调用 `eidClearFrameBuffer` |
| `--dump-features` | 关闭 | 额外导出 `feature_dump.json` |

示例：指定输出目录并延长超时：

```bash
python read_scanner_calibration.py --ip 192.168.1.100 --output D:\calibration_data --timeout-ms 5000
```

调试特征名（新机型适配时）：

```bash
python read_scanner_calibration.py --sn ABC123456 --dump-features
```

### 运行前检查

1. 扫码器已上电，网线/USB 连接正常
2. 厂商配置工具或本工具能枚举到设备（`eidEnumDevices` 成功）
3. 使用 `--sn` 时 SN 与设备标签一致；使用 `--ip` 时 IP 与扫码器当前地址一致
4. 标定场景下，建议在扫码器前放置标准标定码，确保 `scan_result.json` 中 `read_state` 为成功状态

## 输出目录结构

每次运行在 `--output` 下创建子目录，命名格式：

```text
<序列号或IP>_<YYYYMMDD_HHMMSS>/
```

示例：`192.168.1.100_20260518_143052/`

| 文件 | 说明 |
|------|------|
| `device_info.json` | 设备标识与网络信息 |
| `software_config.xml` | 软件 UserSet 配置快照 |
| `hardware_config.xml` | 硬件 UserSet 配置快照 |
| `scan_image.jpg` / `.png` / `.raw` | 采图结果（格式取决于设备输出） |
| `scan_result.json` | 帧元数据、解码状态、条码列表 |
| `feature_dump.json` | 仅在使用 `--dump-features` 时生成 |

### `scan_result.json` 主要字段

- `read_state` / `read_state_name`：读码状态
- `code_num`：识别到的码数量
- `codes[]`：每条码的 `data`、`type_name`、`position`（四角坐标）等
- `image_path`：对应图像文件路径
- `width` / `height` / `is_jpeg`：图像尺寸与格式信息

## 工作流程说明

```mermaid
flowchart LR
    A[枚举设备] --> B[连接扫码器]
    B --> C[保存 device_info]
    C --> D[导出 software_config]
    D --> E[导出 hardware_config]
    E --> F[软触发采图]
    F --> G[保存图像与 scan_result]
    G --> H[断开连接]
```

软触发流程（`scanner_reader.py`）：

1. `eidStartGrabbing` 启动采集
2. 可选清空帧缓冲
3. 尝试设置 TriggerMode=On、TriggerSource=Software
4. 执行软触发命令（如 `TriggerSoftware`）
5. `eidGetFrame` 等待一帧，解析并落盘

不同机型 GenICam 特征名可能不同，项目通过 `scanner_config.py` 中的候选名列表自动匹配；若连接或触发失败，可配合 `--dump-features` 查看实际特征名并调整配置常量。

## 退出码

| 码 | 含义 |
|----|------|
| `0` | 采集成功 |
| `1` | 失败（未找到设备、连接失败、超时、SDK 错误等）；详情见控制台日志 |

## 常见问题

**提示设置 `EASYID_RUNENV_64`**

未配置或路径错误。确认环境变量指向含 `EasyID.dll` 的目录，并重启终端。

**`No scanner device found`**

PC 未发现设备。检查网线、IP 网段、防火墙，或先用官方工具确认枚举是否正常。

**`Device not found for target=...`**

已枚举到设备，但 SN/IP 与参数不一致。核对 `--sn` / `--ip` 是否与 `device_info` 中一致。

**`eidGetFrame` 超时**

增大 `--timeout-ms`；确认触发模式与标定码在视野内；可尝试 `--no-clear-buffer` 对比行为。

**图像为 `.raw` 而非 `.png`**

安装 Pillow：`pip install Pillow`；或设备输出非 Mono8/JPEG，属预期行为。

## 项目结构

```text
easyid-calibration-tool/
├── read_scanner_calibration.py   # CLI 入口
├── scanner_reader.py             # 连接、导出配置、采图流程
├── scanner_config.py               # 特征名与默认参数
├── scanner_utils.py                # SDK 封装与图像/JSON 工具
├── EasyID.py                       # EasyID SDK Python 绑定
└── requirements.txt
```

## 许可证与 SDK

本工具依赖厂商 **EasyID SDK**，使用前请遵守其许可与部署说明。`EasyID.py` 为 SDK 自带或配套的 Python 封装，请勿在未授权环境下分发 `EasyID.dll`。
