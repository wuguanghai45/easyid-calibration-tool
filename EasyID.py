#!/usr/bin/env python
# -*- coding: utf-8 -*-

from ctypes import *
import sys
import os
import platform
from enum import Enum
from pathlib import Path

MAX_DEVICE_NUM = 256

# 加载SDK动态库
# load SDK library
os_name = platform.system()
bits, linkage= platform.architecture()


def _resolve_easyid_runtime_dir(env_path: str, is_64bit: bool) -> tuple[Path, Path]:
    base = Path(env_path).expanduser()
    runtime_name = "x64" if is_64bit else "Win32"
    if base.name.lower() in ("x64", "win32"):
        return base.parent.parent, base
    if (base / "EasyID.dll").is_file():
        return base.parent, base
    runtime_dir = base / "Runtime" / runtime_name
    if runtime_dir.is_file() or (runtime_dir / "EasyID.dll").is_file():
        return base, runtime_dir
    return base.parent, base


def _configure_windows_dll_search(sdk_root: Path, runtime_dir: Path) -> None:
    candidates: list[Path] = []
    if runtime_dir.is_dir():
        candidates.append(runtime_dir)
    for sub in ("x64", "Win32"):
        path = sdk_root / "Runtime" / sub
        if path.is_dir():
            candidates.append(path)
    drivers = sdk_root / "Drivers"
    if drivers.is_dir():
        for dll_dir in drivers.rglob("*"):
            if dll_dir.is_dir() and any(dll_dir.glob("*.dll")):
                candidates.append(dll_dir)

    added: list[str] = []
    seen: set[str] = set()
    for directory in candidates:
        key = str(directory.resolve())
        if key in seen:
            continue
        seen.add(key)
        added.append(key)
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(key)
            except OSError:
                pass
    if added:
        os.environ["PATH"] = os.pathsep.join(added) + os.pathsep + os.environ.get("PATH", "")


if os_name == 'Windows':
    is_64bit = bits == '64bit'
    EASYID_RUNENV = "EASYID_RUNENV_64" if is_64bit else "EASYID_RUNENV_32"
    env_path = os.environ.get(EASYID_RUNENV)
    if env_path is None:
        print(f"Please set the environment variable {EASYID_RUNENV} to the EasyID installation path")
        sys.exit()
    sdk_root, runtime_dir = _resolve_easyid_runtime_dir(env_path, is_64bit)
    lib_path = runtime_dir / "EasyID.dll"
    if not lib_path.is_file():
        print(f"EasyID.dll not found: {lib_path}")
        sys.exit()
    _configure_windows_dll_search(sdk_root, runtime_dir)
    EASYID = WinDLL(str(lib_path))
elif os_name == 'Linux':
        EASYID = CDLL("../../../lib/libEasyID.so")
else:
    print("Unsupported OS")
    sys.exit()

EID_INFO_STR_LEN = 64       # ///< @~chinese 信息字符串最大长度      @~english The maximum length of the information string

# Indicate if pixel is monochrome or RGB
EID_GVSP_PIX_MONO  =  0x01000000
EID_GVSP_PIX_COLOR  =   0x02000000
EID_GVSP_PIX_CUSTOM  =  0x80000000
EID_GVSP_PIX_COLOR_MASK=0xFF000000

# Indicate effective number of bits occupied by the pixel (including padding).
# This can be used to compute amount of memory required to store an image.
def EID_PIXEL_BIT_COUNT(n):
    return n << 16

EidHandle = c_void_p()      #///< @~chinese 通用句柄      @~english Generic handle
EidCamera = c_void_p()      #///< @~chinese 相机句柄      @~english Camera handle
EidFrame =  c_void_p()      #///< @~chinese 帧句柄        @~english Frame handle

# 定义枚举类型
# define enum type
def enum(**enums):
    return type('Enum', (), enums)

# /// @~chinese
# /// @brief 错误码
# /// @~english
# /// @brief Error code
EidError = enum(
    eidErrorOK = 0,                      #///<@~chinese 成功                                 @~english OK
    eidErrorUnknown = 1,                 #///<@~chinese 未知错误                             @~english Unknown error
    eidErrorInternalError = 2,           #///<@~chinese 内部错误                             @~english Internal error
    eidErrorInvalidParameter = 3,        #///<@~chinese 无效参数                             @~english Invalid parameter
    eidErrorNotConnected = 4,            #///<@~chinese 相机未连接                           @~english Camera not connected
    eidErrorNotFound = 5,                #///<@~chinese 未找到                               @~english Not found
    eidErrorTimeout = 6,                 #///<@~chinese 超时                                 @~english Timeout
    eidErrorNotImplemented = 7,          #///<@~chinese 未实现                               @~english Not implemented
    eidErrorRepeatOperation = 8,         #///<@~chinese 重复操作                             @~english Repeat operation
    eidErrorNullPtr = 9,                 #///<@~chinese 空指针                               @~english Null pointer
    eidErrorReadDataFail = 10,           #///<@~chinese 读取数据失败                         @~english Failed to read data
    eidErrorWriteDataFail = 11,          #///<@~chinese 写入数据失败                         @~english Failed to write data
    eidErrorDataCheckFail = 12,          #///<@~chinese 数据校验失败                         @~english Data verification failed
    eidErrorImageSizeError = 13,         #///<@~chinese 图像大小错误                         @~english Wrong image size
    eidErrorImageTypeError = 14,         #///<@~chinese 图像类型错误                         @~english Wrong image type
    eidErrorImageDataTypeError = 15,     #///<@~chinese 图像数据类型错误                     @~english Wrong image data type
    eidErrorSerializeFail = 16,          #///<@~chinese 序列化失败                           @~english Serialization failed
    eidErrorDeserializeFail = 17,        #///<@~chinese 反序列化失败                         @~english Deserialization failed
    eidErrorOpenFileFail = 18,           #///<@~chinese 打开文件失败                         @~english Failed to open file
    eidErrorWriteFileFail = 19,          #///<@~chinese 文件写入失败                         @~english File writing failed
    eidErrorInvalidHandle = 20,          #///<@~chinese 无效句柄                             @~english Invalid handle
    eidErrorInsufficientBuffer = 21,     #///<@~chinese 缓冲区过小                           @~english Insufficient buffer
    eidErrorInvalidIP = 22,			     #///<@~chinese 设备与主机的IP网段不匹配				@~english Device's and PC's subnet is mismatch
    eidErrorConnected = 23			     #///<@~chinese 相机已连接							@~english camera connected
)
# /// @~chinese
# /// @brief 属性类型
# /// @~english
# /// @brief Feature type
EidFeatureType = enum(
    eidFeatureTypeUnknown = 0,               # ///< @~chinese 未定义    @~english Undefined
    eidFeatureTypeInt = 1,                   # ///< @~chinese 整型数    @~english Integer
    eidFeatureTypeFloat = 2,                 # ///< @~chinese 浮点数    @~english Float
    eidFeatureTypeEnum = 3,                  # ///< @~chinese 枚举      @~english Enumeration
    eidFeatureTypeBool = 4,                  # ///< @~chinese 布尔      @~english Bool
    eidFeatureTypeString = 5,                # ///< @~chinese 字符串    @~english String
    eidFeatureTypeCommand = 6,               # ///< @~chinese 命令      @~english Command
    eidFeatureTypeGroup = 7,                 # ///< @~chinese 分组      @~english Group
)

# /// @~chinese
# /// @brief 接口类型
# /// @~english
# /// @brief Interface type
EidInterfaceType = enum(
    eidInterfaceTypeUnknown = 0x00000000,    # ///< @~chinese 未知接口类型    @~english Unknown interface type
    eidInterfaceTypeGige    = 0x00000001,    # ///< @~chinese 网卡接口类型    @~english NIC type
    eidInterfaceTypeUsb     = 0x00000002,    # ///< @~chinese USB接口类型     @~english USB interface type
    eidInterfaceTypeAll     = 0xffffffff     # ///< @~chinese 所有接口类型    @~english All interface type
)

# /// @~chinese
# /// @brief 设备类型
# /// @~english
# /// @brief Device type
EidDeviceType = enum(
    eidDeviceTypeUnknown = 0,                    # ///< @~chinese 未知类型    @~english Unknown type
    eidDeviceTypeGige = 1,                       # ///< @~chinese GIGE相机    @~english GigE Camera
    eidDeviceTypeUSB = 2                         # ///< @~chinese USB相机     @~english USB Camera
)

# /// @~chinese
# /// @brief 设备数据类型, 用于 #eidCreateDevice 函数
# /// @~english
# /// @brief Device data type, used in the #eidCreateDevice function
EidDeviceDataType = enum(
    eidDeviceDataTypeID = 0,                        # ///< @~chinese 设备ID    @~english Device ID
    eidDeviceDataTypeSN = 1,                        # ///< @~chinese 序列号    @~english Serial number
    eidDeviceDataTypeIP = 2,                        # ///< @~chinese IP地址    @~english IP address
    eidDeviceDataTypeMAC = 3                        # ///< @~chinese MAC地址   @~english MAC address
)

# /// @~chinese
# /// @brief 图像像素格式
# /// @~english
# /// @brief Image pixel format
EidPixelFormat = enum(
    eidPixelUnknwon = -1,                           # ///<@~chinese 未知          @~english Unknown

    # // Mono Format
    eidPixelMono1p       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(1) | 0x0037),
    eidPixelMono2p       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(2) | 0x0038),
    eidPixelMono4p       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(4) | 0x0039),
    eidPixelMono8        = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(8) | 0x0001),
    eidPixelMono8S       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(8) | 0x0002),
    eidPixelMono10       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0003),
    eidPixelMono10Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x0004),
    eidPixelMono12       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0005),
    eidPixelMono12Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x0006),
    eidPixelMono14       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0025),
    eidPixelMono16       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0007),

    # // Bayer Format
    eidPixelBayGR8        = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(8) | 0x0008),
    eidPixelBayRG8        = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(8) | 0x0009),
    eidPixelBayGB8        = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(8) | 0x000A),
    eidPixelBayBG8        = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(8) | 0x000B),
    eidPixelBayGR10       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x000C),
    eidPixelBayRG10       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x000D),
    eidPixelBayGB10       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x000E),
    eidPixelBayBG10       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x000F),
    eidPixelBayGR12       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0010),
    eidPixelBayRG12       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0011),
    eidPixelBayGB12       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0012),
    eidPixelBayBG12       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0013),
    eidPixelBayGR10Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x0026),
    eidPixelBayRG10Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x0027),
    eidPixelBayGB10Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x0028),
    eidPixelBayBG10Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x0029),
    eidPixelBayGR12Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x002A),
    eidPixelBayRG12Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x002B),
    eidPixelBayGB12Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x002C),
    eidPixelBayBG12Packed = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(12) | 0x002D),
    eidPixelBayGR16       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x002E),
    eidPixelBayRG16       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x002F),
    eidPixelBayGB16       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0030),
    eidPixelBayBG16       = (EID_GVSP_PIX_MONO | EID_PIXEL_BIT_COUNT(16) | 0x0031),

    # // RGB Format
    eidPixelRGB8          = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(24) | 0x0014),
    eidPixelBGR8          = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(24) | 0x0015),
    eidPixelRGBA8         = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(32) | 0x0016),
    eidPixelBGRA8         = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(32) | 0x0017),
    eidPixelRGB10         = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(48) | 0x0018),
    eidPixelBGR10         = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(48) | 0x0019),
    eidPixelRGB12         = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(48) | 0x001A),
    eidPixelBGR12         = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(48) | 0x001B),
    eidPixelRGB16         = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(48) | 0x0033),
    eidPixelRGB10V1Packed = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(32) | 0x001C),
    eidPixelRGB10P32      = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(32) | 0x001D),
    eidPixelRGB12V1Packed = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(36) | 0X0034),
    eidPixelRGB565P       = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x0035),
    eidPixelBGR565P       = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0X0036),

    # // YUV Format
    eidPixelYUV411_8_UYYVYY         = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(12) | 0x001E),
    eidPixelYUV422_8_UYVY           = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x001F),
    eidPixelYUV422_8                = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x0032),
    eidPixelYUV8_UYV                = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(24) | 0x0020),
    eidPixelYCbCr8CbYCr             = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(24) | 0x003A),
    eidPixelYCbCr422_8              = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x003B),
    eidPixelYCbCr422_8_CbYCrY       = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x0043),
    eidPixelYCbCr411_8_CbYYCrYY     = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(12) | 0x003C),
    eidPixelYCbCr601_8_CbYCr        = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(24) | 0x003D),
    eidPixelYCbCr601_422_8          = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x003E),
    eidPixelYCbCr601_422_8_CbYCrY   = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x0044),
    eidPixelYCbCr601_411_8_CbYYCrYY = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(12) | 0x003F),
    eidPixelYCbCr709_8_CbYCr        = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(24) | 0x0040),
    eidPixelYCbCr709_422_8          = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x0041),
    eidPixelYCbCr709_422_8_CbYCrY   = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(16) | 0x0045),
    eidPixelYCbCr709_411_8_CbYYCrYY = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(12) | 0x0042),

    # // RGB Planar
    eidPixelRGB8Planar  = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(24) | 0x0021),
    eidPixelRGB10Planar = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(48) | 0x0022),
    eidPixelRGB12Planar = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(48) | 0x0023),
    eidPixelRGB16Planar = (EID_GVSP_PIX_COLOR | EID_PIXEL_BIT_COUNT(48) | 0x0024)
)

# /// @~chinese
# /// @brief 读码状态
# /// @~english
# /// @brief Code reading state
EidReadState = enum(
    eidReadStateUnknown = 0,                        # ///<@~chinese 未知    @~english Unknown
    eidReadStateNA = 1,                             # ///<@~chinese 无效    @~english Not available
    eidReadStateComplete = 2,                       # ///<@~chinese 全部    @~english Complete
    eidReadStateNoRead = 3,                         # ///<@~chinese 无条码  @~english No code was read
    eidReadStatePartial = 4,                        # ///<@~chinese 部分    @~english Partial
    eidReadStateFail = 5,                           # ///<@~chinese 失败    @~english Fail
    eidReadStatePhaseNA = 6,                        # ///<@~chinese 无效(Phase模式)    @~english Not available(Phase mode)
    eidReadStatePhaseComplete = 7,                  # ///<@~chinese 全部(Phase模式)    @~english Complete(Phase mode)
    eidReadStatePhaseNoRead = 8,                    # ///<@~chinese 无条码(Phase模式)  @~english No code was read(Phase mode)
    eidReadStatePhasePartial = 9,                   # ///<@~chinese 部分(Phase模式)    @~english Partial(Phase mode)
    eidReadStatePhaseFail = 10                      # ///<@~chinese 失败(Phase模式)    @~english Fail(Phase mode)
)

# /// @~chinese
# /// @brief 码类型
# /// @~english
# /// @brief Barcode type
EidBarcodeType = enum(
    eidCodeTypeUnknown = -1,                        # ///<@~chinese 未知      @~english Unknown

    #// 1D
    eidCodeTypeEAN8 = 0,                            # ///< EAN8
    eidCodeTypeEAN13 = 1,                           # ///< EAN13
    eidCodeTypeCode39 = 2,                          # ///< Code39
    eidCodeTypeCode93 = 3,                          # ///< Code93
    eidCodeTypeCode128 = 4,                         # ///< Code128
    eidCodeTypeUPCA = 5,                            # ///< UPCA
    eidCodeTypeUPCE = 6,                            # ///< UPCE
    eidCodeTypeITF25 = 7,                           # ///< ITF25
    eidCodeTypeCODABAR = 8,                         # ///< CODABAR
    eidCodeTypeCODE128A = 9,                        # ///< CODE128A
    eidCodeTypeCODE128B = 10,                       # ///< CODE128B
    eidCodeTypeCODE128C = 11,                       # ///< CODE128C

    #// 2D
    eidCodeTypeQR = 100,                            # ///< QR
    eidCodeTypeDM = 101,                            # ///< DM
    eidCodeTypePDF417 = 102,                        # ///< PDF417
    eidCodeTypeVERICODE = 103                       # ///< VERICODE
)

# /// @~chinese
# /// @brief 设备连接状态
# /// @~english
# /// @brief Device connection status
EidConnectionState = enum(
    eidConnStateOffline = 0,  # ///<@~chinese 离线    @~english Offline
    eidConnStateOnline = 1    # ///<@~chinese 在线    @~english Online
)

# /// @~chinese
# /// @brief GigE设备信息
# /// @~english
# /// @brief GigE device info
class EidGigeDeviceInfo(Structure):
    pass
EidGigeDeviceInfo._fields_ = [
    ("macAddress", EID_INFO_STR_LEN * c_char),         # ///< @~chinese 设备Mac地址			@~english Device MAC Address
    ("ipAddress", EID_INFO_STR_LEN * c_char),          # ///< @~chinese 设备Ip地址			@~english Device ip Address
    ("subnetMask", EID_INFO_STR_LEN * c_char),         # ///< @~chinese 子网掩码				@~english SubnetMask
    ("defaultGateWay", EID_INFO_STR_LEN * c_char),     # ///< @~chinese 默认网关				@~english Default GateWay
    ("isIpValid", c_bool),
    ("reserved", 767 * c_char)
]

class EidDeviceInfoUnion(Union):
    pass
EidDeviceInfoUnion._fields_ = [
    ("gigeDeviceInfo",EidGigeDeviceInfo)                   # ///< @~chinese  Gige设备信息    @~english Gige device info
]

# /// @~chinese
# /// @brief 设备信息
# /// @~english
# /// @brief Device info
class EidDeviceInfo(Structure):
    pass
EidDeviceInfo._anonymous_ = ("deviceInfoUnion",)
EidDeviceInfo._fields_ = [
    ("deviceType",c_int),                         #///< @~chinese 设备类别       @~english Device type
    ("interfaceType",c_int ),                  #///< @~chinese 接口类别       @~english Interface type
    ("deviceID",c_char * EID_INFO_STR_LEN),               # ///< @~chinese 设备ID         @~english Device ID
    ("cameraName",c_char * EID_INFO_STR_LEN),             # ///< @~chinese 用户自定义名   @~english User defined name
    ("serialNumber",c_char * EID_INFO_STR_LEN),           # ///< @~chinese 设备序列号     @~english Device serial number
    ("vendorName",c_char * EID_INFO_STR_LEN),             # ///< @~chinese 厂商           @~english Device vendor
    ("modelName",c_char * EID_INFO_STR_LEN),              # ///< @~chinese 设备型号       @~english Device model
    ("manufactureInfo",c_char * EID_INFO_STR_LEN),        # ///< @~chinese 设备制造信息   @~english Device manufacture
    ("deviceVersion",c_char * EID_INFO_STR_LEN),          # ///< @~chinese 设备版本       @~english Device version
    ("interfaceName",c_char * 128),                       # ///< @~chinese 接口名         @~english Interface name
    ("reserved",c_char * 440),                            # ///< @~chinese 预留位         @~english Reseved
    ("deviceInfoUnion",EidDeviceInfoUnion)
]

# /// @~chinese
# /// @brief 设备信息列表
# /// @~english
# /// @brief Device information list
class EidDeviceList(Structure):
    pass
EidDeviceList._fields_ = [
    ("num",c_uint32),                                     # ///< @~chinese 设备数量        @~english Device Number
    ("infos",POINTER(EidDeviceInfo)),                     # ///< @~chinese 设备信息列表    @~english Device information list
    ("reserved",c_char * 64)                              # ///< @~chinese 预留位          @~english Reserved
]

# /// @~chinese
# /// @brief 错误列表
# /// @~english
# /// @brief Error list
class EidErrorList(Structure):
    pass
EidErrorList._fields_ = [
    ("num",c_uint32),                                   # ///< @~chinese 失败的属性数量  @~english Number of failed features
    ("names",POINTER(c_char_p)),                        # ///< @~chinese 失败属性名列表  @~english Error feature name list
    ("reserved",c_char * 64)                            # ///< @~chinese 预留位          @~english Reserved
]

# /// @~chinese
# /// @brief 整型属性信息
# /// @~english
# /// @brief int feature information
class EidIntFeatureInfo(Structure):
    pass
EidIntFeatureInfo._fields_ = [
    ("current",c_int64),                                # ///< @~chinese 当前值    @~english Current value
    ("min",c_int64),                                    # ///< @~chinese 最小值    @~english Minimum value
    ("max",c_int64),                                    # ///< @~chinese 最大值    @~english Maximum value
    ("inc",c_int64),                                    # ///< @~chinese 增量      @~english Increment
    ("reserved",c_char * 64)                            # ///< @~chinese 预留位    @~english Reserved
]

# /// @~chinese
# /// @brief 浮点型属性信息
# /// @~english
# /// @brief float feature information
class EidFloatFeatureInfo(Structure):
    pass
EidFloatFeatureInfo._fields_ = [
    ("current",c_double),                                # ///< @~chinese 当前值    @~english Current value
    ("min",c_double),                                    # ///< @~chinese 最小值    @~english Minimum value
    ("max",c_double),                                    # ///< @~chinese 最大值    @~english Maximum value
    ("uinit",c_char * 32),                              # ///< @~chinese 单位      @~english Unit
    ("reserved",c_char * 72)                            # ///< @~chinese 预留位    @~english Reserved
]

# /// @~chinese
# /// @brief 字符串型属性信息
# /// @~english
# /// @brief string feature information
class EidStringFeatureInfo(Structure):
    pass
EidStringFeatureInfo._fields_ = [
    ("maxLen",c_uint32),                                # ///< @~chinese 最大长度  @~english The maximum length of the string
    ("value",c_char * 256),                             # ///< @~chinese 当前值    @~english Current value
    ("reserved",c_char * 64)                            # ///< @~chinese 预留位    @~english Reserved
]

# /// @~chinese
# /// @brief 枚举型属性条目
# /// @~english
# /// @brief enum feature entry
class EidEnumFeatureEntry(Structure):
    pass
EidEnumFeatureEntry._fields_ = [
    ("value",c_uint64),                                 # ///< @~chinese 值    @~english Value
    ("name",c_char * 64)                                # ///< @~chinese 名称  @~english Name
]

# /// @~chinese
# /// @brief 枚举型属性信息
# /// @~english
# /// @brief enum feature information
class EidEnumFeatureEntryList(Structure):
    pass
EidEnumFeatureEntryList._fields_ = [
    ("num",c_int),                                      # ///< @~chinese 数量      @~english Entry count
    ("entryList",EidEnumFeatureEntry * 64)              # ///< @~chinese 条目列表  @~english Entry list
]

# /// @~chinese
# /// @brief 二维坐标点
# /// @~english
# /// @brief 2D coordinate point
class EidPoint(Structure):
    pass
EidPoint._fields_ = [
    ("x",c_int),                                        # ///<@~chinese x坐标        @~english x-coordinate
    ("y",c_int)                                         # ///<@~chinese y坐标        @~english y-coordinate
]

# /// @~chinese
# /// @brief 条码信息
# /// @~english
# /// @brief Barcode information
class EidCodeInfo(Structure):
    pass
EidCodeInfo._fields_ = [
    ("type",c_int),                                     # ///<@~chinese 类型         @~english Code type
    ("ppm",c_float),                                    # ///<@~chinese PPM          @~english PPM
    ("position",EidPoint * 4),                          # ///<@~chinese 位置, 4个点  @~english Position, 4 points
    ("data",c_char_p),                                  # ///<@~chinese 内容         @~english Code content
    ("typeName",c_char_p),                              # ///<@~chinese 类型名称     @~english Code type name
    ("reserved",c_char * 256)                           # ///<@~chinese 预留位       @~english Reserved
]

# /// @~chinese
# /// @brief 帧信息
# /// @~english
# /// @brief Frame information
class EidFrameInfo(Structure):
    pass
EidFrameInfo._fields_ = [
    ("id",c_uint64),                                    # ///<@~chinese 帧ID          @~english Frame block ID
    ("timestamp",c_uint64),                             # ///<@~chinese 时间戳        @~english Timestamp
    ("width",c_uint32),                                 # ///<@~chinese 图像宽度      @~english Image width
    ("height",c_uint32),                                # ///<@~chinese 图像高度      @~english Image height
    ("format",c_int),                                   # ///<@~chinese 像素格式      @~english Pixel format
    ("readState",c_int),                                # ///<@~chinese 读码状态      @~english Code reading state
    ("codeNum",c_uint32),                               # ///<@~chinese 条码数量      @~english Number of barcodes
    ("imageDataLen",c_uint32),                          # ///<@~chinese 图像数据长度  @~english Length of image data
    ("imageData",POINTER(c_uint8)),                      # ///<@~chinese 图像数据      @~english Image data
    ("codeList",POINTER(EidCodeInfo)),                  # ///<@~chinese 条码信息列    @~english Barcode information list
    ("isJpeg",c_bool),                                  # ///<@~chinese 是否jpeg图    @~english Is jpeg image
    ("reserved",c_char * 255)                           # ///<@~chinese 预留位        @~english Reserved
]

# /// @~chinese
# /// @brief 连接信息
# /// @~english
# /// @brief Connetion information
class EidConnectionInfo(Structure):
    pass
EidConnectionInfo._fields_ = [
    ("state",c_int),                                    # ///<@~chinese 连接状态    @~english Connetion state
    ("reserved",c_char * 64)                            # ///<@~chinese 预留位      @~english Reserved
]

# typedef void(EASYID_CALL* EidFrameCallback)(const EidFrameInfo* frameInfo, void* userData);
EidFrameCallback = eval('CFUNCTYPE')(None, POINTER(EidFrameInfo), c_void_p)

# typedef void(EASYID_CALL* EidConnectionCallback)(const EidConnectionInfo* info, void* userData);
EidConnectionCallback = eval('CFUNCTYPE')(None, POINTER(EidConnectionInfo), c_void_p)

# typedef void(EASYID_CALL* EidFeatureUpdateCallback)(const char* name, void* userData);
EidFeatureUpdateCallback = eval('CFUNCTYPE')(None, c_char_p, c_void_p)

# typedef void(EASYID_CALL* EidEnumFeatureChildrenCallback)(const char* name, void* userData);
EidEnumFeatureChildrenCallback = eval('CFUNCTYPE')(None, c_char_p, c_void_p)

class Camera():
    def __init__(self):
        self.handle = c_void_p()  # 创建句柄指针
        self.framehandle = c_void_p()  # 创建句柄指针

    @staticmethod
    def eidGetVersion() -> bytes:
        EASYID.eidGetVersion.restype = c_char_p
        # C原型：EASYID_API const char* EASYID_CALL eidGetVersion();
        return EASYID.eidGetVersion()

    @staticmethod
    def eidEnumDevices(deviceList: EidDeviceList, type: int) -> int:
        EASYID.eidEnumDevices.argtypes = (POINTER(EidDeviceList), c_uint32)
        EASYID.eidEnumDevices.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidEnumDevices(EidDeviceList* deviceList, uint32_t type);
        return EASYID.eidEnumDevices(byref(deviceList), c_uint32(type))

    def eidCreateDevice(self, data: str, type: int) -> int:
        # Match official SDK Python binding: returns camera handle pointer.
        EASYID.eidCreateDevice.argtypes = (c_char_p, c_int)
        EASYID.eidCreateDevice.restype = POINTER(c_void_p)
        # C原型:EASYID_API EidCamera EASYID_CALL eidCreateDevice(const char* data, EidDeviceDataType type);
        if isinstance(data, str):
            payload: str | bytes = data
        else:
            payload = data
        self.handle = EASYID.eidCreateDevice(payload, c_int(type))
        if not self.handle:
            return EidError.eidErrorInvalidParameter
        return EidError.eidErrorOK

    def eidReleaseFrame(self) -> None:
        EASYID.eidReleaseHandle.argtypes = c_void_p
        EASYID.eidReleaseHandle.restype = None
        # C原型:EASYID_API void EASYID_CALL eidReleaseHandle(EidHandle handle);
        return EASYID.eidReleaseHandle(self.framehandle)

    def eidReleaseHandle(self) -> None:
        EASYID.eidReleaseHandle.argtypes = c_void_p
        EASYID.eidReleaseHandle.restype = None
        # C原型:EASYID_API void EASYID_CALL eidReleaseHandle(EidHandle handle);
        return EASYID.eidReleaseHandle(self.handle)

    def eidGetDeviceInfo(self, info: EidDeviceInfo) -> int:
        EASYID.eidGetDeviceInfo.argtypes = (c_void_p, POINTER(EidDeviceInfo))
        EASYID.eidGetDeviceInfo.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetDeviceInfo(EidCamera camera, EidDeviceInfo* info);
        return EASYID.eidGetDeviceInfo(self.handle, byref(info))

    def eidOpenDevice(self) -> int:
        EASYID.eidOpenDevice.argtypes = c_void_p
        EASYID.eidOpenDevice.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidOpenDevice(EidCamera camera);
        return EASYID.eidOpenDevice(self.handle)

    def eidCloseDevice(self) -> int:
        EASYID.eidCloseDevice.argtypes = c_void_p
        EASYID.eidCloseDevice.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidCloseDevice(EidCamera camera);
        return EASYID.eidCloseDevice(self.handle)

    def eidIsDeviceOpen(self) -> int:
        EASYID.eidIsDeviceOpen.argtypes = c_void_p
        EASYID.eidIsDeviceOpen.restype = c_int
        # C原型:EASYID_API bool EASYID_CALL eidIsDeviceOpen(EidCamera camera);
        return EASYID.eidIsDeviceOpen(self.handle)

    def eidForceIpAddress(self, ipAddr: str, subnetMask: str, gateway: str) -> int:
        EASYID.eidForceIpAddress.argtypes = (c_void_p, c_char_p, c_char_p, c_char_p)
        EASYID.eidForceIpAddress.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidForceIpAddress(EidCamera camera, const char* ipAddr, const char* subnetMask, const char* gateway);
        return EASYID.eidForceIpAddress(self.handle, ipAddr.encode("ascii"), subnetMask.encode("ascii"), gateway.encode("ascii"))

    def eidDownloadGenICamXML(self, path: str) -> int:
        EASYID.eidDownloadGenICamXML.argtypes = (c_void_p, c_char_p)
        EASYID.eidDownloadGenICamXML.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidDownloadGenICamXML(EidCamera camera, const char* path);
        return EASYID.eidDownloadGenICamXML(self.handle, path.encode("ascii"))

    def eidSaveDeviceConfig(self, path: str) -> int:
        EASYID.eidSaveDeviceConfig.argtypes = (c_void_p, c_char_p)
        EASYID.eidSaveDeviceConfig.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidSaveDeviceConfig(EidCamera camera, const char* path);
        return EASYID.eidSaveDeviceConfig(self.handle, path.encode("ascii"))

    def eidLoadDeviceConfig(self, path: str, errorList: EidErrorList) -> int:
        EASYID.eidLoadDeviceConfig.argtypes = (c_void_p, c_char_p, POINTER(EidErrorList))
        EASYID.eidLoadDeviceConfig.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidLoadDeviceConfig(EidCamera camera, const char* path, EidErrorList* errorList);
        return EASYID.eidLoadDeviceConfig(self.handle, path.encode("ascii"), byref(errorList))

    def eidGetFeatureType(self, name: str) -> int:
        EASYID.eidGetFeatureType.argtypes = (c_void_p, c_char_p)
        EASYID.eidGetFeatureType.restype = c_int
        # C原型:EASYID_API EidFeatureType EASYID_CALL eidGetFeatureType(EidCamera camera, const char* name);
        return EASYID.eidGetFeatureType(self.handle, name.encode("ascii"))

    def eidIsFeatureValid(self, name: str) -> bool:
        EASYID.eidIsFeatureValid.argtypes = (c_void_p, c_char_p)
        EASYID.eidIsFeatureValid.restype = c_bool
        # C原型:EASYID_API bool EASYID_CALL eidIsFeatureValid(EidCamera camera, const char* name);
        return EASYID.eidIsFeatureValid(self.handle, name.encode("ascii"))

    def eidIsFeatureAvailable(self, name: str) -> bool:
        EASYID.eidIsFeatureAvailable.argtypes = (c_void_p, c_char_p)
        EASYID.eidIsFeatureAvailable.restype = c_bool
        # C原型:EASYID_API bool EASYID_CALL eidIsFeatureAvailable(EidCamera camera, const char* name);
        return EASYID.eidIsFeatureAvailable(self.handle, name.encode("ascii"))

    def eidIsFeatureReadable(self, name: str) -> bool:
        EASYID.eidIsFeatureReadable.argtypes = (c_void_p, c_char_p)
        EASYID.eidIsFeatureReadable.restype = c_bool
        # C原型:EASYID_API bool EASYID_CALL eidIsFeatureReadable(EidCamera camera, const char* name);
        return EASYID.eidIsFeatureReadable(self.handle, name.encode("ascii"))

    def eidIsFeatureWriteable(self, name: str) -> bool:
        EASYID.eidIsFeatureWriteable.argtypes = (c_void_p, c_char_p)
        EASYID.eidIsFeatureWriteable.restype = c_bool
        # C原型:EASYID_API bool EASYID_CALL eidIsFeatureWriteable(EidCamera camera, const char* name);
        return EASYID.eidIsFeatureWriteable(self.handle, name.encode("ascii"))

    def eidGetIntFeatureValue(self, name: str, value: c_int64) -> int:
        EASYID.eidGetIntFeatureValue.argtypes = (c_void_p, c_char_p, POINTER(c_int64))
        EASYID.eidGetIntFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetIntFeatureValue(EidCamera camera, const char* name, int64_t* value);
        return EASYID.eidGetIntFeatureValue(self.handle, name.encode("ascii"), byref(value))

    def eidSetIntFeatureValue(self, name: str, value: int) -> int:
        EASYID.eidSetIntFeatureValue.argtypes = (c_void_p, c_char_p, c_int64)
        EASYID.eidSetIntFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidSetIntFeatureValue(EidCamera camera, const char* name, int64_t value);
        return EASYID.eidSetIntFeatureValue(self.handle, name.encode("ascii"), c_int64(value))

    def eidGetIntFeatureInfo(self, name: str, info: EidIntFeatureInfo) -> int:
        EASYID.eidGetIntFeatureInfo.argtypes = (c_void_p, c_char_p, POINTER(EidIntFeatureInfo))
        EASYID.eidGetIntFeatureInfo.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetIntFeatureInfo(EidCamera camera, const char* name, EidIntFeatureInfo* info);
        return EASYID.eidGetIntFeatureInfo(self.handle, name.encode("ascii"), byref(info))

    def eidGetFloatFeatureValue(self, name: str, value: c_double) -> int:
        EASYID.eidGetFloatFeatureValue.argtypes = (c_void_p, c_char_p, POINTER(c_double))
        EASYID.eidGetFloatFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetFloatFeatureValue(EidCamera camera, const char* name, double* value);
        return EASYID.eidGetFloatFeatureValue(self.handle, name.encode("ascii"), byref(value))

    def eidSetFloatFeatureValue(self, name: str, value: float) -> int:
        EASYID.eidSetFloatFeatureValue.argtypes = (c_void_p, c_char_p, c_double)
        EASYID.eidSetFloatFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidSetFloatFeatureValue(EidCamera camera, const char* name, double value);
        return EASYID.eidSetFloatFeatureValue(self.handle, name.encode("ascii"), c_double(value))

    def eidGetFloatFeatureInfo(self, name: str, info: EidFloatFeatureInfo) -> int:
        EASYID.eidGetFloatFeatureInfo.argtypes = (c_void_p, c_char_p, POINTER(EidFloatFeatureInfo))
        EASYID.eidGetFloatFeatureInfo.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetFloatFeatureInfo(EidCamera camera, const char* name, EidFloatFeatureInfo* info);
        return EASYID.eidGetFloatFeatureInfo(self.handle, name.encode("ascii"), byref(info))

    def eidGetBoolFeatureValue(self, name: str, value: c_bool) -> int:
        EASYID.eidGetBoolFeatureValue.argtypes = (c_void_p, c_char_p, POINTER(c_bool))
        EASYID.eidGetBoolFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetBoolFeatureValue(EidCamera camera, const char* name, bool* value);
        return EASYID.eidGetBoolFeatureValue(self.handle, name.encode("ascii"), byref(value))

    def eidSetBoolFeatureValue(self, name: str, value: bool) -> int:
        EASYID.eidSetBoolFeatureValue.argtypes = (c_void_p, c_char_p, c_bool)
        EASYID.eidSetBoolFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidSetBoolFeatureValue(EidCamera camera, const char* name, bool value);
        return EASYID.eidSetBoolFeatureValue(self.handle, name.encode("ascii"), c_bool(value))

    def eidGetStringFeatureValue(self, name: str, value: c_char_p, size: c_uint32) -> int:
        EASYID.eidGetStringFeatureValue.argtypes = (c_void_p, c_char_p, c_char_p, POINTER(c_uint32))
        EASYID.eidGetStringFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetStringFeatureValue(EidCamera camera, const char* name, char* value, uint32_t* size);
        return EASYID.eidGetStringFeatureValue(self.handle, name.encode("ascii"), value, byref(size))

    def eidSetStringFeatureValue(self, name: str, value: str) -> int:
        EASYID.eidSetStringFeatureValue.argtypes = (c_void_p, c_char_p, c_char_p)
        EASYID.eidSetStringFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidSetStringFeatureValue(EidCamera camera, const char* name, const char* value);
        return EASYID.eidSetStringFeatureValue(self.handle, name.encode("ascii"), value.encode("utf-8"))

    def eidGetStringFeatureInfo(self, name: str, info: EidStringFeatureInfo) -> int:
        EASYID.eidGetStringFeatureInfo.argtypes = (c_void_p, c_char_p, POINTER(EidStringFeatureInfo))
        EASYID.eidGetStringFeatureInfo.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetStringFeatureInfo(EidCamera camera, const char* name, EidStringFeatureInfo* info);
        return EASYID.eidGetStringFeatureInfo(self.handle, name.encode("ascii"), byref(info))

    def eidGetEnumFeatureValue(self, name: str, value: c_uint64) -> int:
        EASYID.eidGetEnumFeatureValue.argtypes = (c_void_p, c_char_p, POINTER(c_uint64))
        EASYID.eidGetEnumFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetEnumFeatureValue(EidCamera camera, const char* name, uint64_t* value);
        return EASYID.eidGetEnumFeatureValue(self.handle, name.encode("ascii"), byref(value))

    def eidSetEnumFeatureValue(self, name: str, value: int) -> int:
        EASYID.eidSetEnumFeatureValue.argtypes = (c_void_p, c_char_p, c_uint64)
        EASYID.eidSetEnumFeatureValue.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidSetEnumFeatureValue(EidCamera camera, const char* name, uint64_t value);
        return EASYID.eidSetEnumFeatureValue(self.handle, name.encode("ascii"), c_uint64(value))

    def eidGetEnumFeatureSymbol(self, name: str, value: c_char_p, size: c_uint32) -> int:
        EASYID.eidGetEnumFeatureSymbol.argtypes = (c_void_p, c_char_p, c_char_p, c_uint32)
        EASYID.eidGetEnumFeatureSymbol.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetEnumFeatureSymbol(EidCamera camera, const char* name, char* value, uint32_t size);
        return EASYID.eidGetEnumFeatureSymbol(self.handle, name.encode("ascii"), value, c_uint32(size))

    def eidSetEnumFeatureSymbol(self, name: str, value: str) -> int:
        EASYID.eidSetEnumFeatureSymbol.argtypes = (c_void_p, c_char_p, c_char_p)
        EASYID.eidSetEnumFeatureSymbol.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidSetEnumFeatureSymbol(EidCamera camera, const char* name, const char* value);
        return EASYID.eidSetEnumFeatureSymbol(self.handle, name.encode("ascii"), value.encode("ascii"))

    def eidGetEnumFeatureEntryList(self, name: str, entryList: EidEnumFeatureEntryList) -> int:
        EASYID.eidGetEnumFeatureEntryList.argtypes = (c_void_p, c_char_p, POINTER(EidEnumFeatureEntryList))
        EASYID.eidGetEnumFeatureEntryList.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetEnumFeatureEntryList(EidCamera camera, const char* name, EidEnumFeatureEntryList* entryList);
        return EASYID.eidGetEnumFeatureEntryList(self.handle, name.encode("ascii"), byref(entryList))

    def eidExecCommandFeature(self, name: str) -> int:
        EASYID.eidExecCommandFeature.argtypes = (c_void_p, c_char_p)
        EASYID.eidExecCommandFeature.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidExecCommandFeature(EidCamera camera, const char* name);
        return EASYID.eidExecCommandFeature(self.handle, name.encode("ascii"))

    def eidEnumFeatureChildren(self, name: str, fn, userData: c_void_p) -> int:
        EASYID.eidEnumFeatureChildren.argtypes = (c_void_p, c_char_p, c_void_p, c_void_p)
        EASYID.eidEnumFeatureChildren.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidEnumFeatureChildren(EidCamera camera, const char* name, EidEnumFeatureChildrenCallback fn, void* userData);
        return EASYID.eidEnumFeatureChildren(self.handle, name.encode("ascii"), fn, userData)

    def eidStartGrabbing(self, bufferCount: int) -> int:
        EASYID.eidStartGrabbing.argtypes = (c_void_p, c_int)
        EASYID.eidStartGrabbing.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidStartGrabbing(EidCamera camera, int bufferCount);
        return EASYID.eidStartGrabbing(self.handle, c_int(bufferCount))

    def eidStopGrabbing(self) -> int:
        EASYID.eidStopGrabbing.argtypes = (c_void_p)
        EASYID.eidStopGrabbing.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidStopGrabbing(EidCamera camera);
        return EASYID.eidStopGrabbing(self.handle)

    def eidIsGrabbing(self) -> int:
        EASYID.eidIsGrabbing.argtypes = (c_void_p)
        EASYID.eidIsGrabbing.restype = c_int
        # C原型:EASYID_API bool EASYID_CALL eidIsGrabbing(EidCamera camera);
        return EASYID.eidIsGrabbing(self.handle)

    def eidClearFrameBuffer(self) -> int:
        EASYID.eidClearFrameBuffer.argtypes = (c_void_p)
        EASYID.eidClearFrameBuffer.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidClearFrameBuffer(EidCamera camera);
        return EASYID.eidClearFrameBuffer(self.handle)

    def eidGetFrame(self, timeout: int) -> int:
        EASYID.eidGetFrame.argtypes = (c_void_p, c_uint32)
        EASYID.eidGetFrame.restype = POINTER(c_void_p)
        # C原型:EASYID_API EidFrame EASYID_CALL eidGetFrame(EidCamera camera, uint32_t timeout);
        self.framehandle = EASYID.eidGetFrame(self.handle, c_uint32(timeout))
        if bool(self.framehandle) == False: 
            return 3
        return 0

    def eidIsFrameValid(self) -> bool:
        EASYID.eidIsFrameValid.argtypes = (c_void_p)
        EASYID.eidIsFrameValid.restype = c_bool
        # C原型:EASYID_API bool EASYID_CALL eidIsFrameValid(EidFrame frame);
        return EASYID.eidIsFrameValid(self.framehandle)

    def eidGetFrameInfo(self, info: EidFrameInfo) -> int:
        EASYID.eidGetFrameInfo.argtypes = (c_void_p, POINTER(EidFrameInfo))
        EASYID.eidGetFrameInfo.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidGetFrameInfo(EidFrame frame, EidFrameInfo* info);
        return EASYID.eidGetFrameInfo(self.framehandle, byref(info))

    def eidRegisterFrameCallback(self, cb, userData: c_void_p) -> int:
        EASYID.eidRegisterFrameCallback.argtypes = (c_void_p, c_void_p, c_void_p)
        EASYID.eidRegisterFrameCallback.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidRegisterFrameCallback(EidCamera camera, EidFrameCallback cb, void* userData);
        return EASYID.eidRegisterFrameCallback(self.handle, cb, userData)

    def eidRegisterConnectionCallback(self, cb, userData: c_void_p) -> int:
        EASYID.eidRegisterConnectionCallback.argtypes = (c_void_p, c_void_p, c_void_p)
        EASYID.eidRegisterConnectionCallback.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidRegisterConnectionCallback(EidCamera camera, EidConnectionCallback cb, void* userData);
        return EASYID.eidRegisterConnectionCallback(self.handle, cb, userData)

    def eidRegisterFeatureUpdateCallback(self, cb, userData: c_void_p) -> int:
        EASYID.eidRegisterFeatureUpdateCallback.argtypes = (c_void_p, c_void_p, c_void_p)
        EASYID.eidRegisterFeatureUpdateCallback.restype = c_int
        # C原型:EASYID_API int EASYID_CALL eidRegisterFeatureUpdateCallback(EidCamera camera, EidFeatureUpdateCallback cb, void* userData);
        return EASYID.eidRegisterFeatureUpdateCallback(self.handle, cb, userData)