"""Continuous frame preview for MJPEG streaming."""

from __future__ import annotations

import logging
import queue
import threading
import time
from ctypes import POINTER, c_char_p, c_ubyte, cast
from pathlib import Path
from tempfile import gettempdir
from typing import TYPE_CHECKING

from imv_sdk.IMVDefines import IMV_ESaveType, IMV_Frame, IMV_OK, IMV_SaveImageToFileParam

from scanner.feature import try_first_enum
from scanner_config import DEFAULT_BUFFER_COUNT, TRIGGER_MODE_FEATURES
from scanner_utils import ScannerProtocolError

if TYPE_CHECKING:
    from imv_sdk.IMVApi import MvCamera

logger = logging.getLogger(__name__)

TRIGGER_MODE_OFF_SYMBOLS = ("Off", "False")


def configure_free_run(cam: MvCamera) -> None:
    """Set trigger off for continuous acquisition."""
    for feature in TRIGGER_MODE_FEATURES:
        if try_first_enum(cam, feature, TRIGGER_MODE_OFF_SYMBOLS):
            return
    logger.warning("Could not set trigger mode to Off for free-run preview")


def _encode_frame_jpeg(cam: MvCamera, frame: IMV_Frame, seq: int) -> bytes:
    tmp = Path(gettempdir()) / f"imv_preview_{seq % 32}.jpg"
    save_param = IMV_SaveImageToFileParam()
    save_param.nWidth = frame.frameInfo.width
    save_param.nHeight = frame.frameInfo.height
    save_param.nPixelFormat = frame.frameInfo.pixelFormat
    save_param.pSrcData = cast(frame.pData, POINTER(c_ubyte))
    save_param.nSrcDataLen = frame.frameInfo.size
    save_param.eImageType = IMV_ESaveType.typeImageJpeg
    save_param.nQuality = 85
    save_param.nBayerDemosaic = 2
    save_param.pImagePath = c_char_p(str(tmp).encode("utf-8"))

    ret = cam.IMV_SaveImageToFile(save_param)
    if ret != IMV_OK or not tmp.is_file():
        raise ScannerProtocolError(f"IMV_SaveImageToFile failed: {ret}")
    data = tmp.read_bytes()
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    return data


class PreviewStream:
    """Grab frames in a background thread and expose JPEG bytes via a queue."""

    def __init__(
        self,
        cam: MvCamera,
        *,
        buffer_count: int = DEFAULT_BUFFER_COUNT,
        frame_timeout_ms: int = 500,
        max_queue: int = 2,
    ) -> None:
        self._cam = cam
        self._buffer_count = max(buffer_count, 1)
        self._frame_timeout_ms = max(frame_timeout_ms, 100)
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._seq = 0

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        configure_free_run(self._cam)
        ret = self._cam.IMV_SetBufferCount(self._buffer_count)
        if ret != IMV_OK:
            logger.warning("IMV_SetBufferCount failed: %d", ret)

        ret = self._cam.IMV_StartGrabbing()
        if ret != IMV_OK:
            raise ScannerProtocolError(f"IMV_StartGrabbing failed: {ret}")

        self._stop.clear()
        self._running = True
        self._thread = threading.Thread(target=self._grab_loop, name="PreviewStream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._running = False
        try:
            self._cam.IMV_StopGrabbing()
        except Exception:
            pass
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def get_frame(self, timeout: float = 2.0) -> bytes | None:
        try:
            item = self._queue.get(timeout=timeout)
            return item
        except queue.Empty:
            return None

    def _grab_loop(self) -> None:
        frame = IMV_Frame()
        try:
            while not self._stop.is_set():
                ret = self._cam.IMV_GetFrame(frame, self._frame_timeout_ms)
                if ret != IMV_OK:
                    continue
                try:
                    jpeg = _encode_frame_jpeg(self._cam, frame, self._seq)
                    self._seq += 1
                    try:
                        self._queue.put_nowait(jpeg)
                    except queue.Full:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self._queue.put_nowait(jpeg)
                        except queue.Full:
                            pass
                except ScannerProtocolError:
                    logger.debug("Preview JPEG encode failed", exc_info=True)
                finally:
                    self._cam.IMV_ReleaseFrame(frame)
        finally:
            self._running = False
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
