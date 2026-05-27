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

export function normalizeVin(raw: string): string {
  return raw.replace(/[\x00-\x1f\x7f]/g, "").trim();
}

export function isCameraScanSupported(): boolean {
  return Boolean(navigator.mediaDevices?.getUserMedia) && window.isSecureContext;
}

export function cameraScanUnsupportedReason(): string | null {
  if (!navigator.mediaDevices?.getUserMedia) {
    return "当前浏览器不支持摄像头访问。";
  }
  if (!window.isSecureContext) {
    return "摄像头扫码需要 HTTPS 或 localhost 安全上下文。";
  }
  return null;
}

export async function startVinCamera(): Promise<MediaStream> {
  const reason = cameraScanUnsupportedReason();
  if (reason) {
    throw new Error(reason);
  }

  try {
    return await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
  } catch {
    return await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
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
