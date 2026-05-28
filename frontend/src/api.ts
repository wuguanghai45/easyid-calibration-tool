import type { ConfigField, DeviceListItem, LogEntry, ScanResult } from "./types";

const API = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  return res.json() as Promise<T>;
}

export async function scanVinSerial() {
  return request<{ ok: boolean; vin?: string; error?: string }>("/vin/scan", {
    method: "POST",
  });
}

export async function listDevices(interfaceName?: string) {
  const q = interfaceName ? `?interface=${encodeURIComponent(interfaceName)}` : "";
  return request<{ devices: DeviceListItem[]; error?: string }>(`/devices${q}`);
}

export async function connect(params: {
  sn?: string;
  ip?: string;
  interface?: string;
  tcp_port?: number;
}) {
  return request<{ ok: boolean; error?: string; device?: DeviceListItem }>("/connect", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function disconnect() {
  return request<{ ok: boolean }>("/disconnect", { method: "POST" });
}

export async function getDeviceStatus() {
  return request<{
    connected: boolean;
    device?: DeviceListItem;
    preview_running: boolean;
    tcp_connected: boolean;
    tcp_port: number;
    sdk_version?: string;
  }>("/device");
}

export async function getConfig() {
  return request<{ ok: boolean; fields?: ConfigField[]; error?: string }>("/config");
}

export async function importConfig(persist = true) {
  return request<{
    ok: boolean;
    fields?: ConfigField[];
    error?: string;
    failed_params?: string[];
    config_path?: string;
    userset_saved?: boolean;
  }>("/config/import", {
    method: "POST",
    body: JSON.stringify({ persist }),
  });
}

export async function putConfig(updates: Record<string, unknown>, persist = true) {
  return request<{ ok: boolean; fields?: ConfigField[]; error?: string }>("/config", {
    method: "PUT",
    body: JSON.stringify({ updates, persist }),
  });
}

export async function getLatestScan() {
  return request<{ ok: boolean; scan: ScanResult | null }>("/scan/latest");
}

export async function syncCameraOffset(vin: string, theta: number) {
  return request<{
    ok: boolean;
    record_id?: string;
    vin?: string;
    theta?: number;
    error?: string;
  }>("/feishu/camera-offset", {
    method: "POST",
    body: JSON.stringify({ vin, theta }),
  });
}

export async function getLogs(limit = 200) {
  return request<{ logs: LogEntry[] }>(`/logs?limit=${limit}`);
}

export async function clearLogs() {
  return request<{ ok: boolean }>("/logs", { method: "DELETE" });
}

export function mjpegUrl() {
  return `${API}/stream/mjpeg`;
}

export function scanWebSocketUrl() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${API}/ws/scan`;
}
