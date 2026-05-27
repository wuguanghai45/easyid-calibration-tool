/** Browser camera barcode scanning for VIN / frame number input. */

import { BrowserMultiFormatReader, type IScannerControls } from "@zxing/browser";

const BARCODE_FORMATS = [
  "qr_code",
  "code_128",
  "code_39",
  "code_93",
  "datamatrix",
  "ean_13",
  "ean_8",
] as const;

const SCAN_TIMEOUT_MS = 60_000;

type LegacyGetUserMedia = (
  constraints: MediaStreamConstraints,
  onSuccess: (stream: MediaStream) => void,
  onError: (error: Error) => void
) => void;

type NavigatorWithLegacy = Navigator & {
  getUserMedia?: LegacyGetUserMedia;
  webkitGetUserMedia?: LegacyGetUserMedia;
  mozGetUserMedia?: LegacyGetUserMedia;
};

export function normalizeVin(raw: string): string {
  return raw.replace(/[\x00-\x1f\x7f]/g, "").trim();
}

function isLocalhostHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

/** Resolve getUserMedia across modern and legacy browser APIs. */
export function resolveGetUserMedia():
  | ((constraints: MediaStreamConstraints) => Promise<MediaStream>)
  | null {
  if (navigator.mediaDevices?.getUserMedia) {
    return (constraints) => navigator.mediaDevices.getUserMedia(constraints);
  }

  const legacyNav = navigator as unknown as NavigatorWithLegacy;
  const legacyFn =
    legacyNav.getUserMedia ?? legacyNav.webkitGetUserMedia ?? legacyNav.mozGetUserMedia;
  const legacy = legacyFn?.bind(navigator);

  if (!legacy) {
    return null;
  }

  return (constraints) =>
    new Promise<MediaStream>((resolve, reject) => {
      legacy(constraints, resolve, reject);
    });
}

export function isCameraScanSupported(): boolean {
  return Boolean(resolveGetUserMedia()) && window.isSecureContext;
}

export function cameraScanUnsupportedReason(): string | null {
  const { hostname, origin, port, protocol } = window.location;
  const defaultPort = port || (protocol === "https:" ? "443" : "80");

  if (!window.isSecureContext) {
    if (isLocalhostHost(hostname)) {
      return `当前页面非安全上下文（${origin}），无法使用摄像头。请检查是否被嵌入 iframe 或使用了受限模式。`;
    }
    return (
      `无法在非 HTTPS 地址上使用摄像头（当前：${origin}）。` +
      `若在本机操作，请改用 http://localhost:${defaultPort}；` +
      `若需用手机或其它设备扫码，请使用 HTTPS 启动服务：` +
      `python run_web.py --ssl --port ${defaultPort}，然后用 https://<本机IP>:${defaultPort} 访问并接受证书提示。`
    );
  }

  if (!resolveGetUserMedia()) {
    return "当前浏览器不提供摄像头 API，请使用 Chrome、Edge 或 Safari 最新版本。";
  }

  return null;
}

export async function startVinCamera(): Promise<MediaStream> {
  const reason = cameraScanUnsupportedReason();
  if (reason) {
    throw new Error(reason);
  }

  const getUserMedia = resolveGetUserMedia();
  if (!getUserMedia) {
    throw new Error("当前浏览器不提供摄像头 API。");
  }

  try {
    return await getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
  } catch {
    return await getUserMedia({ video: true, audio: false });
  }
}

export function stopVinCamera(stream: MediaStream | null | undefined): void {
  stream?.getTracks().forEach((track) => track.stop());
}

function createBarcodeDetector(): BarcodeDetector | null {
  if (typeof BarcodeDetector === "undefined") {
    return null;
  }
  try {
    return new BarcodeDetector({ formats: [...BARCODE_FORMATS] });
  } catch {
    try {
      return new BarcodeDetector();
    } catch {
      return null;
    }
  }
}

export type VinScanSession = {
  stop: () => void;
};

/** Start decoding from a live video element; calls onResult once with a non-empty VIN. */
export function startVinScanLoop(
  video: HTMLVideoElement,
  onResult: (vin: string) => void
): VinScanSession {
  let stopped = false;
  let rafId = 0;
  let zxingControls: IScannerControls | null = null;

  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
    zxingControls?.stop();
    zxingControls = null;
  };

  const emitIfValid = (raw: string) => {
    const vin = normalizeVin(raw);
    if (!vin || stopped) return false;
    onResult(vin);
    stop();
    return true;
  };

  const detector = createBarcodeDetector();

  if (detector) {
    const tick = async () => {
      if (stopped) return;
      if (video.readyState >= HTMLMediaElement.HAVE_ENOUGH_DATA) {
        try {
          const barcodes = await detector.detect(video);
          for (const code of barcodes) {
            if (emitIfValid(code.rawValue)) return;
          }
        } catch {
          /* ignore per-frame detection errors */
        }
      }
      rafId = requestAnimationFrame(() => {
        void tick();
      });
    };
    rafId = requestAnimationFrame(() => {
      void tick();
    });
  } else {
    const zxingReader = new BrowserMultiFormatReader();
    zxingControls = zxingReader.scan(video, (result) => {
      if (stopped || !result) return;
      emitIfValid(result.getText());
    });
  }

  return { stop };
}

export const VIN_SCAN_TIMEOUT_MS = SCAN_TIMEOUT_MS;
