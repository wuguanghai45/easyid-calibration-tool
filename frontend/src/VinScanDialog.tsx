import { useEffect, useRef, useState } from "react";
import {
  cameraScanUnsupportedReason,
  startVinCamera,
  startVinScanLoop,
  stopVinCamera,
  VIN_SCAN_TIMEOUT_MS,
} from "./vinScanner";

type ScanPhase = "starting" | "scanning" | "error";

export type VinScanDialogProps = {
  open: boolean;
  onClose: () => void;
  onScanned: (vin: string) => void;
};

export function VinScanDialog({ open, onClose, onScanned }: VinScanDialogProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scanSessionRef = useRef<{ stop: () => void } | null>(null);
  const [phase, setPhase] = useState<ScanPhase>("starting");
  const [message, setMessage] = useState("正在启动摄像头…");

  useEffect(() => {
    if (!open) {
      return;
    }

    let cancelled = false;
    const unsupported = cameraScanUnsupportedReason();
    if (unsupported) {
      setPhase("error");
      setMessage(unsupported);
      return;
    }

    setPhase("starting");
    setMessage("正在启动摄像头…");

    const cleanup = () => {
      scanSessionRef.current?.stop();
      scanSessionRef.current = null;
      stopVinCamera(streamRef.current);
      streamRef.current = null;
      const video = videoRef.current;
      if (video) {
        video.srcObject = null;
      }
    };

    const timeoutId = window.setTimeout(() => {
      if (cancelled) return;
      setPhase("error");
      setMessage("60 秒内未识别到条码，请调整距离或光线后重试。");
      cleanup();
    }, VIN_SCAN_TIMEOUT_MS);

    void (async () => {
      try {
        const stream = await startVinCamera();
        if (cancelled) {
          stopVinCamera(stream);
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (!video) {
          stopVinCamera(stream);
          return;
        }
        video.srcObject = stream;
        await video.play();
        if (cancelled) {
          cleanup();
          return;
        }
        setPhase("scanning");
        setMessage("将条码对准画面中央");
        scanSessionRef.current = startVinScanLoop(video, (vin) => {
          window.clearTimeout(timeoutId);
          onScanned(vin);
        });
      } catch (err) {
        if (cancelled) return;
        setPhase("error");
        const name = err instanceof DOMException ? err.name : "";
        if (name === "NotAllowedError" || name === "PermissionDeniedError") {
          setMessage("摄像头权限被拒绝，请在浏览器设置中允许访问摄像头。");
        } else if (name === "NotFoundError" || name === "DevicesNotFoundError") {
          setMessage("未检测到摄像头设备。");
        } else {
          setMessage(err instanceof Error ? err.message : "无法启动摄像头。");
        }
        cleanup();
      }
    })();

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
      cleanup();
    };
  }, [open, onScanned]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="vin-scan-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="vin-scan-title"
    >
      <div className="vin-scan-dialog-panel">
        <h2 id="vin-scan-title" className="vin-scan-dialog-title">
          扫描车架号
        </h2>
        <p className="vin-scan-dialog-message">{message}</p>
        <div className="vin-scan-video-wrap">
          <video
            ref={videoRef}
            className="vin-scan-video"
            autoPlay
            playsInline
            muted
            aria-hidden={phase === "error"}
          />
        </div>
        <button type="button" className="vin-scan-cancel" onClick={onClose}>
          取消
        </button>
      </div>
    </div>
  );
}
