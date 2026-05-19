"""Frame capture with soft trigger via IMV SDK."""

from __future__ import annotations

import logging
import time
from ctypes import c_char_p, cast, POINTER, c_ubyte
from pathlib import Path
from typing import Any, TYPE_CHECKING

from imv_sdk.IMVDefines import IMV_ESaveType, IMV_Frame, IMV_OK, IMV_SaveImageToFileParam

from scanner.chunk_parser import frame_pixel_bytes, parse_frame_bytes, parse_frame_chunks
from scanner.trigger import configure_soft_trigger, fire_software_trigger, try_enable_chunk_mode
from scanner_utils import ScannerProtocolError, save_frame_image

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)


def _clear_frame_buffer(cam: MvCamera, *, attempts: int = 8, timeout_ms: int = 50) -> None:
    frame = IMV_Frame()
    for _ in range(attempts):
        ret = cam.IMV_GetFrame(frame, timeout_ms)
        if ret != IMV_OK:
            break
        cam.IMV_ReleaseFrame(frame)


def _save_frame_to_file(cam: MvCamera, frame: IMV_Frame, image_path: Path) -> Path:
    save_param = IMV_SaveImageToFileParam()
    save_param.nWidth = frame.frameInfo.width
    save_param.nHeight = frame.frameInfo.height
    save_param.nPixelFormat = frame.frameInfo.pixelFormat
    save_param.pSrcData = cast(frame.pData, POINTER(c_ubyte))
    save_param.nSrcDataLen = frame.frameInfo.size
    save_param.eImageType = IMV_ESaveType.typeImageJpeg
    save_param.nQuality = 90
    save_param.nBayerDemosaic = 2
    save_param.pImagePath = c_char_p(str(image_path).encode("utf-8"))

    ret = cam.IMV_SaveImageToFile(save_param)
    if ret == IMV_OK and image_path.is_file():
        return image_path
    raise ScannerProtocolError(f"IMV_SaveImageToFile failed with error code {ret}")


def capture_soft_trigger_frame(
    cam: MvCamera,
    output_dir: Path,
    *,
    timeout_ms: int,
    buffer_count: int,
    clear_buffer: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    try_enable_chunk_mode(cam)
    configure_soft_trigger(cam)

    ret = cam.IMV_SetBufferCount(max(buffer_count, 1))
    if ret != IMV_OK:
        logger.warning("IMV_SetBufferCount failed: %d", ret)

    ret = cam.IMV_StartGrabbing()
    if ret != IMV_OK:
        raise ScannerProtocolError(f"IMV_StartGrabbing failed with error code {ret}")

    frame = IMV_Frame()
    try:
        if clear_buffer:
            sdk_ret = cam.IMV_ClearFrameBuffer()
            if sdk_ret != IMV_OK:
                _clear_frame_buffer(cam)

        fire_software_trigger(cam)

        ret = cam.IMV_GetFrame(frame, max(timeout_ms, 200))
        if ret != IMV_OK:
            raise ScannerProtocolError(f"IMV_GetFrame timed out or failed with error code {ret}")

        width = int(frame.frameInfo.width)
        height = int(frame.frameInfo.height)
        pixel_format = int(frame.frameInfo.pixelFormat)
        raw_bytes = frame_pixel_bytes(frame)

        image_base = output_dir / "scan_image"
        jpg_path = image_base.with_suffix(".jpg")
        try:
            image_path = _save_frame_to_file(cam, frame, jpg_path)
            is_jpeg = True
        except ScannerProtocolError:
            logger.warning("SDK JPEG save failed; falling back to raw/PNG saver.")
            is_jpeg = raw_bytes[:3] == b"\xff\xd8\xff"
            image_path = save_frame_image(
                image_base,
                raw_bytes,
                is_jpeg=is_jpeg,
                width=width,
                height=height,
            )

        chunk_payload = parse_frame_chunks(cam, frame)
        if chunk_payload.get("code_num", 0) == 0:
            byte_payload = parse_frame_bytes(raw_bytes)
            for key in ("read_state", "read_state_name", "code_num", "codes"):
                if byte_payload.get(key):
                    chunk_payload[key] = byte_payload[key]

        payload: dict[str, Any] = {
            "frame_id": int(frame.frameInfo.blockId),
            "timestamp": int(time.time() * 1_000_000_000),
            "width": width,
            "height": height,
            "pixel_format": pixel_format,
            "image_data_len": len(raw_bytes),
            "is_jpeg": is_jpeg,
            **chunk_payload,
            "image_path": str(image_path),
        }
        return payload
    finally:
        if frame.pData:
            cam.IMV_ReleaseFrame(frame)
        cam.IMV_StopGrabbing()
