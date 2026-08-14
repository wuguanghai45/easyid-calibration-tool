"""FastAPI application for DataMatrix calibration web dashboard."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from feishu.config import FeishuSettings, load_dotenv_if_present
from feishu.errors import FeishuApiError
from feishu.update_camera_offset import run_update
from scanner.vin_serial import VinSerialError, scan_vin_once
from scanner_utils import ScannerProtocolError
from web.session import get_session

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _connect_hint(error: str) -> str:
    if "-101" in error or "error code -101" in error:
        return (
            "Close other programs using the camera (e.g. MVS), ensure the PC NIC is on the "
            "same subnet as the device, wait a few seconds and connect again."
        )
    if "-107" in error or "subnet" in error.lower():
        return "Add a static IPv4 on the camera NIC in the same subnet as the device (e.g. x.x.x.10/24)."
    return ""


app = FastAPI(title="DataMatrix Calibration Bench", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectRequest(BaseModel):
    sn: str | None = None
    ip: str | None = None
    interface: str | None = None
    tcp_port: int = 3000
    start_preview: bool = True
    start_tcp: bool = True


class ConfigUpdateRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)
    persist: bool = True


class ConfigImportRequest(BaseModel):
    persist: bool = True


class FeishuCameraOffsetRequest(BaseModel):
    vin: str = Field(
        ...,
        min_length=1,
        description="Frame number; matches Bitable S/N column (default S/N*)",
    )
    theta: float = Field(..., description="cameraOffsetTheta in degrees")


@app.on_event("startup")
async def on_startup() -> None:
    load_dotenv_if_present()
    session = get_session()
    session.set_event_loop(asyncio.get_running_loop())
    session.logs.add("info", "Web server started")


@app.post("/api/vin/scan")
async def api_vin_scan(passive: bool = False) -> dict[str, Any]:
    session = get_session()
    try:
        vin = await asyncio.to_thread(scan_vin_once)
    except VinSerialError as exc:
        if not passive:
            session.logs.add("error", f"VIN serial scan failed: {exc}")
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        if not passive:
            session.logs.add("error", f"VIN serial scan failed: {exc}")
        return {"ok": False, "error": str(exc)}

    session.logs.add("info", f"VIN serial scan ok: {vin!r}")
    return {"ok": True, "vin": vin}


@app.get("/api/devices")
def api_list_devices(interface: str | None = None) -> dict[str, Any]:
    session = get_session()
    try:
        devices = session.list_devices(interface=interface)
        return {"devices": devices}
    except Exception as exc:
        session.logs.add("error", f"List devices failed: {exc}")
        return {"devices": [], "error": str(exc)}


@app.post("/api/connect")
def api_connect(body: ConnectRequest) -> dict[str, Any]:
    session = get_session()
    try:
        result = session.connect(
            serial_number=body.sn,
            ip=body.ip,
            interface=body.interface,
            tcp_port=body.tcp_port,
            start_preview=body.start_preview,
            start_tcp=body.start_tcp,
        )
        return {"ok": True, **result}
    except ScannerProtocolError as exc:
        session.logs.add("error", str(exc))
        return {"ok": False, "error": str(exc), "hint": _connect_hint(str(exc))}
    except Exception as exc:
        session.logs.add("error", f"Connect failed: {exc}")
        return {"ok": False, "error": str(exc)}


@app.post("/api/disconnect")
def api_disconnect() -> dict[str, Any]:
    session = get_session()
    session.disconnect()
    return {"ok": True}


@app.get("/api/device")
def api_device_status() -> dict[str, Any]:
    return get_session().get_device_status()


@app.get("/api/config")
def api_get_config() -> dict[str, Any]:
    session = get_session()
    try:
        return {"ok": True, **session.read_config()}
    except ScannerProtocolError as exc:
        return {"ok": False, "error": str(exc)}


@app.put("/api/config")
def api_put_config(body: ConfigUpdateRequest) -> dict[str, Any]:
    session = get_session()
    try:
        result = session.write_config(body.updates, persist=body.persist)
        return {"ok": True, **result}
    except ScannerProtocolError as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/config/import")
def api_import_config(body: ConfigImportRequest | None = None) -> dict[str, Any]:
    session = get_session()
    persist = body.persist if body is not None else True
    try:
        result = session.import_config(persist=persist)
        return {"ok": True, **result}
    except ScannerProtocolError as exc:
        session.logs.add("error", f"Config import failed: {exc}")
        return {"ok": False, "error": str(exc)}


@app.get("/api/config/export")
def api_export_config() -> dict[str, Any]:
    session = get_session()
    import tempfile

    out = Path(tempfile.mkdtemp(prefix="calib_export_"))
    try:
        paths = session.export_configs(out)
        summary = {name: Path(path).name for name, path in paths.items()}
        return {"ok": True, "output_dir": str(out), "files": summary}
    except ScannerProtocolError as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/preview/start")
def api_preview_start() -> dict[str, Any]:
    session = get_session()
    try:
        session.start_preview()
        return {"ok": True, "preview_running": session.preview_running}
    except ScannerProtocolError as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/preview/stop")
def api_preview_stop() -> dict[str, Any]:
    session = get_session()
    session.stop_preview()
    return {"ok": True, "preview_running": False}


@app.get("/api/scan/latest")
def api_scan_latest() -> dict[str, Any]:
    session = get_session()
    latest = session.get_latest_scan()
    return {"ok": True, "scan": latest}


@app.post("/api/feishu/camera-offset")
def api_feishu_camera_offset(body: FeishuCameraOffsetRequest) -> dict[str, Any]:
    session = get_session()
    vin = body.vin.strip()
    if not vin:
        return {"ok": False, "error": "车架号不能为空。"}

    try:
        settings = FeishuSettings.from_env()
        summary = run_update(settings, sn=vin, theta=body.theta)
    except ValueError as exc:
        session.logs.add("error", f"Feishu config: {exc}")
        return {"ok": False, "error": str(exc)}
    except FeishuApiError as exc:
        session.logs.add("error", f"Feishu sync failed: {exc}")
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        session.logs.add("error", f"Feishu sync failed: {exc}")
        return {"ok": False, "error": str(exc)}

    session.logs.add(
        "info",
        f"Feishu updated record_id={summary['record_id']} "
        f"{summary.get('sn_field', 'SN*')}={vin!r} theta={summary['theta']}",
    )
    return {
        "ok": True,
        "record_id": summary["record_id"],
        "vin": vin,
        "theta": summary["theta"],
    }


@app.get("/api/logs")
def api_logs(limit: int = 200) -> dict[str, Any]:
    session = get_session()
    return {"logs": session.logs.list(limit=limit)}


@app.delete("/api/logs")
def api_clear_logs() -> dict[str, Any]:
    get_session().logs.clear()
    return {"ok": True}


async def mjpeg_generator():
    session = get_session()
    boundary = b"--frame"
    while True:
        if not session.preview_running:
            await asyncio.sleep(0.2)
            continue
        frame = await asyncio.to_thread(session.get_preview_frame, 2.0)
        if frame is None:
            await asyncio.sleep(0.05)
            continue
        yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"


@app.get("/api/stream/mjpeg")
async def api_mjpeg_stream() -> StreamingResponse:
    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/api/ws/scan")
async def ws_scan(websocket: WebSocket) -> None:
    await websocket.accept()
    session = get_session()
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    session.register_ws_queue(queue)
    try:
        latest = session.get_latest_scan()
        if latest:
            await websocket.send_json(latest)
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(item)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "ts": asyncio.get_event_loop().time()})
    except WebSocketDisconnect:
        pass
    finally:
        session.unregister_ws_queue(queue)


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
