import * as api from "./api";
import type { ConfigField, DeviceListItem, FlowStep, ScanResult } from "./types";

export const OFFSET_LIMIT = 20;
export const ANGLE_LIMIT_DEG = 5;
export const SCAN_POLL_MS = 500;
export const SCAN_TIMEOUT_MS = 30_000;

export const STEP_LABELS = ["扫描成功", "绑定成功", "配置成功", "标定成功"] as const;
export const STEP_SHORT_LABELS = ["扫描", "绑定", "配置", "标定"] as const;
export const FEISHU_STEP_SHORT_LABEL = "飞书同步";
export const FEISHU_STEP_LABEL = "飞书同步成功";
export const END_STEP_TITLE = "结束";
export const TOTAL_PROGRESS_STEPS =
  STEP_SHORT_LABELS.length + 1; /* calibration + Feishu */

const CONFIG_DETAIL_KEYS: Record<string, string> = {
  exposure_time_us: "曝光",
  gain: "增益",
  timeout_ms: "超时",
  trigger_mode: "触发模式",
};

export type UiState = "idle" | "running" | "success" | "failure";

/** Incremental progress while runRealCalibration executes. */
export type CalibrationProgress = {
  completedSteps: FlowStep[];
  /** 0-based index of the step currently in progress. */
  activeIndex: number;
};

export type CalibrationOutcome =
  | { ok: true; steps: FlowStep[]; scan: ScanResult; hint: string }
  | { ok: false; steps: FlowStep[]; hint: string };

function joinDetail(parts: Array<string | undefined | null>): string | undefined {
  const filtered = parts.filter((p): p is string => Boolean(p && p.trim()));
  return filtered.length > 0 ? filtered.join("，") : undefined;
}

const FAILED_PARAMS_DISPLAY_MAX = 8;

function formatFailedParams(failedParams: string[]): string {
  if (failedParams.length === 0) {
    return "";
  }
  if (failedParams.length <= FAILED_PARAMS_DISPLAY_MAX) {
    return failedParams.join(", ");
  }
  const shown = failedParams.slice(0, FAILED_PARAMS_DISPLAY_MAX).join(", ");
  return `${shown} 等 ${failedParams.length} 项`;
}

function flowStep(id: string, title: string, detail?: string): FlowStep {
  return detail ? { id, title, detail } : { id, title };
}

/** Map 0–360° device reading to signed offset in (-180, 180]. */
export function normalizeThetaOffsetDeg(deg: number): number {
  if (deg > 180) return deg - 360;
  if (deg < -180) return deg + 360;
  return deg;
}

export function formatOffsetValues(scan: ScanResult): string {
  const theta = normalizeThetaOffsetDeg(scan.theta_deg);
  return `Δx=${scan.x_offset}, Δy=${scan.y_offset}, θ=${theta.toFixed(1)}°`;
}

export function buildScanDetail(device: DeviceListItem): string | undefined {
  return joinDetail([
    device.model_name ? `型号 ${device.model_name}` : undefined,
    device.ip_address ? `IP ${device.ip_address}` : undefined,
    device.vendor_name ? `厂商 ${device.vendor_name}` : undefined,
    device.camera_type ? `类型 ${device.camera_type}` : undefined,
  ]);
}

export function buildBindDetail(device: DeviceListItem): string | undefined {
  const parts: Array<string | undefined> = [];
  if (device.serial_number) {
    parts.push(`扫码器SN ${device.serial_number}`);
  }
  if (device.ip_reconfigured && device.ip_after) {
    const change =
      device.ip_before && device.ip_before !== device.ip_after
        ? `IP ${device.ip_before} → ${device.ip_after}`
        : `IP ${device.ip_after}`;
    parts.push(change);
  } else if (device.ip_recovered && device.ip_after) {
    parts.push(`IP 恢复为 ${device.ip_after}`);
  }
  return joinDetail(parts);
}

export function buildConfigDetail(
  fields: ConfigField[],
  failedParams: string[] = []
): string | undefined {
  const highlights: string[] = [];
  for (const field of fields) {
    const label = CONFIG_DETAIL_KEYS[field.key];
    if (!label || field.value == null || field.value === "") {
      continue;
    }
    highlights.push(`${label}=${field.value}`);
  }

  const failedSummary = formatFailedParams(failedParams);
  if (failedSummary) {
    highlights.push(`部分参数未生效: ${failedSummary}`);
  }

  if (highlights.length > 0) {
    return joinDetail(highlights);
  }
  if (fields.length > 0) {
    return `已导入 ${fields.length} 项配置`;
  }
  if (failedSummary) {
    return `部分参数未生效: ${failedSummary}`;
  }
  return "配置已导入";
}

export function buildCalibrationDetail(scan: ScanResult): string | undefined {
  const parts: Array<string | undefined> = [formatOffsetValues(scan)];
  if (scan.code?.trim()) {
    parts.push(`码 ${scan.code.trim()}`);
  }
  return joinDetail(parts);
}

export function buildFeishuDetail(res: {
  ok: boolean;
  record_id?: string;
  vin?: string;
  theta?: number;
}): string | undefined {
  if (!res.ok) {
    return undefined;
  }
  return joinDetail([
    res.theta != null ? `θ=${res.theta}°` : undefined,
    res.vin ? `S/N ${res.vin}` : undefined,
  ]);
}

export function isCalibrationPass(scan: ScanResult): boolean {
  const theta = normalizeThetaOffsetDeg(scan.theta_deg);
  return (
    Math.abs(scan.x_offset) <= OFFSET_LIMIT &&
    Math.abs(scan.y_offset) <= OFFSET_LIMIT &&
    Math.abs(theta) < ANGLE_LIMIT_DEG
  );
}

export function formatCalibrationHint(scan: ScanResult, passed: boolean): string {
  const values = formatOffsetValues(scan);
  if (passed) {
    return `相机外参标定完成。（${values}）`;
  }
  return `偏移超限：${values}（要求 |Δx|,|Δy|≤${OFFSET_LIMIT}，|θ|<${ANGLE_LIMIT_DEG}°）`;
}

/** Steps that map to the top progress bar (excludes "结束"). */
export function progressCompletedCount(steps: FlowStep[]): number {
  return Math.min(
    steps.filter((s) => s.id !== "end").length,
    TOTAL_PROGRESS_STEPS
  );
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

export async function runRealCalibration(
  onProgress?: (progress: CalibrationProgress) => void
): Promise<CalibrationOutcome> {
  const steps: FlowStep[] = [];

  const notify = (activeIndex: number) => {
    onProgress?.({ completedSteps: [...steps], activeIndex });
  };

  notify(0);

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

  const device: DeviceListItem = devices[0];
  steps.push(flowStep("scan", STEP_LABELS[0], buildScanDetail(device)));
  notify(1);

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

  const connectedDevice = connectRes.device ?? device;
  steps.push(flowStep("bind", STEP_LABELS[1], buildBindDetail(connectedDevice)));
  notify(2);

  const configRes = await api.importConfig();
  if (!configRes.ok) {
    return {
      ok: false,
      steps,
      hint: `配置失败：${configRes.error || "导入配置失败"}`,
    };
  }

  steps.push(
    flowStep(
      "config",
      STEP_LABELS[2],
      buildConfigDetail(configRes.fields ?? [], configRes.failed_params ?? [])
    )
  );
  notify(3);

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
    steps.push(flowStep("calibrate", STEP_LABELS[3], buildCalibrationDetail(scan)));
  }

  return {
    ok: passed,
    steps,
    scan,
    hint: formatCalibrationHint(scan, passed),
  };
}
