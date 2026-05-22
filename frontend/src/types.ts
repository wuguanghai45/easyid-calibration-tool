export interface DeviceInfo {
  model_name?: string;
  serial_number?: string;
  ip_address?: string;
  mac_address?: string;
  camera_type?: string;
  device_version?: string;
  vendor_name?: string;
}

export interface DeviceListItem extends DeviceInfo {
  index: number;
  interface_name?: string;
}

export interface ConfigField {
  key: string;
  feature: string | null;
  value: number | string | null;
  writable: boolean;
  value_type: string;
}

export interface ScanResult {
  x_offset: number;
  y_offset: number;
  theta: number;
  theta_deg: number;
  code: string;
  ts: number;
  type?: string;
}

export interface CalibrationRecord {
  key: string;
  time: string;
  frameNo: string;
  datamatrix: string;
  deltaX: number;
  deltaY: number;
  deltaTheta: number;
  status: string;
}

export interface LogEntry {
  ts: number;
  level: string;
  message: string;
}
