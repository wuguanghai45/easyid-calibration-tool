import * as api from "./api";
import type { DeviceListItem, ScanResult } from "./types";

export const OFFSET_LIMIT = 20;
export const ANGLE_LIMIT_DEG = 5;
export const SCAN_POLL_MS = 500;
export const SCAN_TIMEOUT_MS = 30_000;

export const STEP_LABELS = ["扫描成功", "绑定成功", "配置成功", "标定成功"] as const;

export type UiState = "idle" | "running" | "success" | "failure";

export type CalibrationOutcome =
  | { ok: true; steps: string[]; scan: ScanResult; hint: string }
  | { ok: false; steps: string[]; hint: string };

export function isCalibrationPass(scan: ScanResult): boolean {
  return (
    Math.abs(scan.x_offset) <= OFFSET_LIMIT &&
    Math.abs(scan.y_offset) <= OFFSET_LIMIT &&
    Math.abs(scan.theta_deg) < ANGLE_LIMIT_DEG
  );
}

export function formatCalibrationHint(scan: ScanResult, passed: boolean): string {
  const values = `Δx=${scan.x_offset}, Δy=${scan.y_offset}, θ=${scan.theta_deg.toFixed(1)}°`;
  if (passed) {
    return `相机外参标定完成。（${values}）`;
  }
  return `偏移超限：${values}（要求 |Δx|,|Δy|≤${OFFSET_LIMIT}，|θ|<${ANGLE_LIMIT_DEG}°）`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function waitForScan(
  deadlineMs = SCAN_TIMEOUT_MS,
  pollMs = SCAN_POLL_MS
): Promise<ScanResult | null> {
  const deadline = Date.now() + deadlineMs;
  while (Date.now() < deadline) {
    const res = await api.getLatestScan();
    if (res.scan) {
      return res.scan;
    }
    await sleep(pollMs);
  }
  return null;
}

export async function runRealCalibration(): Promise<CalibrationOutcome> {
  const steps: string[] = [];

  const listRes = await api.listDevices();
  if (listRes.error) {
    return { ok: false, steps, hint: `扫描失败：${listRes.error}` };
  }

  const devices = listRes.devices || [];
  if (devices.length === 0) {
    return { ok: false, steps, hint: "扫描失败：未发现扫码器设备。" };
  }
  if (devices.length > 1) {
    return {
      ok: false,
      steps,
      hint: `扫描失败：发现 ${devices.length} 台设备，请确保仅连接一台扫码器。`,
    };
  }

  steps.push(STEP_LABELS[0]);

  const device: DeviceListItem = devices[0];
  const connectRes = await api.connect({
    sn: device.serial_number,
    ip: device.ip_address,
    tcp_port: 3000,
  });
  if (!connectRes.ok) {
    const hintText =
      "hint" in connectRes && typeof connectRes.hint === "string" ? connectRes.hint : "";
    const msg = connectRes.error || "连接失败";
    return {
      ok: false,
      steps,
      hint: hintText ? `绑定失败：${msg} — ${hintText}` : `绑定失败：${msg}`,
    };
  }

  steps.push(STEP_LABELS[1]);

  const configRes = await api.getConfig();
  if (!configRes.ok) {
    return {
      ok: false,
      steps,
      hint: `配置失败：${configRes.error || "读取配置失败"}`,
    };
  }

  steps.push(STEP_LABELS[2]);

  const scan = await waitForScan();
  if (!scan) {
    return {
      ok: false,
      steps,
      hint: "标定失败：30 秒内未收到扫码数据，请触发扫码后重试。",
    };
  }

  const passed = isCalibrationPass(scan);
  if (passed) {
    steps.push(STEP_LABELS[3]);
  }

  return {
    ok: passed,
    steps,
    scan,
    hint: formatCalibrationHint(scan, passed),
  };
}

export async function runMockCalibration(failAtStepIndex: number): Promise<CalibrationOutcome> {
  const steps: string[] = [];
  for (let i = 0; i < STEP_LABELS.length; i += 1) {
    await sleep(900);
    if (i === failAtStepIndex) {
      return {
        ok: false,
        steps,
        hint: "流程中断，请检查车辆连接与配置。",
      };
    }
    steps.push(STEP_LABELS[i]);
  }

  const mockScan: ScanResult = {
    x_offset: 0,
    y_offset: 0,
    theta: 0,
    theta_deg: 0,
    code: "MOCK",
    ts: Date.now() / 1000,
  };

  return {
    ok: true,
    steps,
    scan: mockScan,
    hint: "相机外参标定完成。",
  };
}
