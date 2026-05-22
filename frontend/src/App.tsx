import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Layout,
  Menu,
  message,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  ApiOutlined,
  CameraOutlined,
  ClearOutlined,
  DownloadOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  ScanOutlined,
  SettingOutlined,
  StopOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import type { MenuProps } from "antd";
import * as api from "./api";
import type { CalibrationRecord, ConfigField, DeviceListItem, LogEntry, ScanResult } from "./types";

const { Sider, Content } = Layout;
const { Title, Text } = Typography;

const FIELD_LABELS: Record<string, string> = {
  exposure_time_us: "曝光时间 (us)",
  gain: "增益",
  timeout_ms: "超时时间 (ms)",
  trigger_mode: "触发模式",
  trigger_source: "触发源",
};

function formatTime(ts: number) {
  return new Date(ts * 1000).toLocaleString("zh-CN");
}

export default function App() {
  const [menuKey, setMenuKey] = useState("calibration");
  const [devices, setDevices] = useState<DeviceListItem[]>([]);
  const [connected, setConnected] = useState(false);
  const [device, setDevice] = useState<DeviceListItem | null>(null);
  const [configFields, setConfigFields] = useState<ConfigField[]>([]);
  const [configForm] = Form.useForm();
  const [currentScan, setCurrentScan] = useState<ScanResult | null>(null);
  const [records, setRecords] = useState<CalibrationRecord[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [frameNo, setFrameNo] = useState("");
  const [continuous, setContinuous] = useState(false);
  const [searchFrame, setSearchFrame] = useState("");
  const [loading, setLoading] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);

  const refreshDevices = useCallback(async () => {
    const res = await api.listDevices();
    setDevices(res.devices || []);
    if (res.error) message.warning(res.error);
  }, []);

  const refreshStatus = useCallback(async () => {
    const st = await api.getDeviceStatus();
    setConnected(st.connected);
    setDevice(st.device || null);
    if (st.connected) setPreviewKey((k) => k + 1);
  }, []);

  const refreshLogs = useCallback(async () => {
    const res = await api.getLogs();
    setLogs(res.logs || []);
  }, []);

  const loadConfig = useCallback(async () => {
    const res = await api.getConfig();
    if (!res.ok) {
      message.error(res.error || "读取配置失败");
      return;
    }
    const fields = res.fields || [];
    setConfigFields(fields);
    const values: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.value !== null && f.value !== undefined) values[f.key] = f.value;
    }
    configForm.setFieldsValue(values);
    message.success("配置已读取");
  }, [configForm]);

  const connectDevice = async (d: DeviceListItem) => {
    setLoading(true);
    try {
      const res = await api.connect({
        sn: d.serial_number,
        ip: d.ip_address,
        tcp_port: 3000,
      });
      if (!res.ok) {
        message.error(res.error || "连接失败");
        return;
      }
      setConnected(true);
      setDevice(res.device || d);
      setPreviewKey((k) => k + 1);
      message.success("设备已连接");
      await loadConfig();
      await refreshLogs();
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    await api.disconnect();
    setConnected(false);
    setDevice(null);
    setCurrentScan(null);
    setPreviewKey((k) => k + 1);
    wsRef.current?.close();
    wsRef.current = null;
    message.info("已断开连接");
    await refreshLogs();
  };

  const saveConfig = async () => {
    const values = configForm.getFieldsValue();
    const updates: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(values)) {
      if (v !== undefined && v !== null && v !== "") updates[k] = v;
    }
    const res = await api.putConfig(updates);
    if (!res.ok) {
      message.error(res.error || "写入配置失败");
      return;
    }
    if (res.fields) {
      setConfigFields(res.fields);
      const next: Record<string, unknown> = {};
      for (const f of res.fields) {
        if (f.value !== null) next[f.key] = f.value;
      }
      configForm.setFieldsValue(next);
    }
    message.success("配置已写入");
    await refreshLogs();
  };

  const addRecord = useCallback(
    (scan: ScanResult) => {
      const rec: CalibrationRecord = {
        key: `${scan.ts}-${scan.code}`,
        time: formatTime(scan.ts),
        frameNo: frameNo || "-",
        datamatrix: scan.code,
        deltaX: scan.x_offset,
        deltaY: scan.y_offset,
        deltaTheta: scan.theta_deg,
        status: "OK",
      };
      setRecords((prev) => [rec, ...prev].slice(0, 500));
    },
    [frameNo]
  );

  useEffect(() => {
    refreshDevices();
    refreshStatus();
    refreshLogs();
    const t = setInterval(refreshLogs, 5000);
    return () => clearInterval(t);
  }, [refreshDevices, refreshStatus, refreshLogs]);

  useEffect(() => {
    if (!connected) {
      wsRef.current?.close();
      wsRef.current = null;
      return;
    }
    const ws = new WebSocket(api.scanWebSocketUrl());
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data) as ScanResult;
      if (data.type === "ping") return;
      setCurrentScan(data);
      if (continuous) addRecord(data);
    };
    ws.onerror = () => message.warning("扫码 WebSocket 连接异常");
    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [connected, continuous, addRecord]);

  const filteredRecords = useMemo(() => {
    if (!searchFrame.trim()) return records;
    const q = searchFrame.trim().toLowerCase();
    return records.filter((r) => r.frameNo.toLowerCase().includes(q));
  }, [records, searchFrame]);

  const exportCsv = () => {
    const header = "时间,车架号,DATAMATRIX,DELTA X,DELTA Y,DELTA θ,状态\n";
    const rows = filteredRecords
      .map(
        (r) =>
          `${r.time},${r.frameNo},${r.datamatrix},${r.deltaX},${r.deltaY},${r.deltaTheta},${r.status}`
      )
      .join("\n");
    const blob = new Blob(["\ufeff" + header + rows], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "calibration_records.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const captureOnce = async () => {
    const res = await api.getLatestScan();
    if (res.scan) {
      setCurrentScan(res.scan);
      addRecord(res.scan);
      message.success("已锁定当前扫码结果");
    } else {
      message.warning("暂无扫码数据，请确保 TCP 结果流已连接");
    }
  };

  const menuItems: MenuProps["items"] = [
    { key: "device", icon: <ApiOutlined />, label: "设备" },
    { key: "config", icon: <SettingOutlined />, label: "配置" },
    { key: "calibration", icon: <ScanOutlined />, label: "校准" },
    { key: "records", icon: <UnorderedListOutlined />, label: "记录" },
  ];

  const renderDeviceCard = () => (
    <Card
      title="设备发现"
      extra={
        <Button icon={<ReloadOutlined />} onClick={refreshDevices}>
          刷新设备
        </Button>
      }
    >
      {connected && device ? (
        <Space direction="vertical" style={{ width: "100%" }}>
          <Title level={5} style={{ margin: 0 }}>
            {device.model_name}
          </Title>
          <Text type="secondary">SN: {device.serial_number}</Text>
          <Space>
            <Tag color="blue">{device.ip_address}</Tag>
            <Badge status="success" text="已连接" />
          </Space>
          <Space wrap>
            <Text>固件: {device.device_version || "-"}</Text>
            <Text>传输: TCP:3000</Text>
          </Space>
          <Button danger onClick={handleDisconnect}>
            断开连接
          </Button>
        </Space>
      ) : (
        <Table
          size="small"
          rowKey={(r) => `${r.index}-${r.serial_number}`}
          dataSource={devices}
          pagination={false}
          columns={[
            { title: "型号", dataIndex: "model_name", key: "model" },
            { title: "序列号", dataIndex: "serial_number", key: "sn" },
            { title: "IP", dataIndex: "ip_address", key: "ip" },
            {
              title: "操作",
              key: "action",
              render: (_, row) => (
                <Button type="link" loading={loading} onClick={() => connectDevice(row)}>
                  连接
                </Button>
              ),
            },
          ]}
        />
      )}
    </Card>
  );

  const renderConfigCard = () => (
    <Card
      title="扫码器配置"
      extra={
        <Space>
          <Button onClick={loadConfig} disabled={!connected}>
            读取
          </Button>
          <Button type="primary" onClick={saveConfig} disabled={!connected}>
            写入
          </Button>
        </Space>
      }
    >
      <Form form={configForm} layout="vertical" disabled={!connected}>
        {(configFields.length ? configFields : Object.keys(FIELD_LABELS).map((k) => ({ key: k }))).map(
          (f: { key: string; writable?: boolean; value?: unknown }) => (
            <Form.Item
              key={f.key}
              name={f.key}
              label={FIELD_LABELS[f.key] || f.key}
            >
              {f.key.includes("trigger") ? (
                <Input />
              ) : (
                <InputNumber style={{ width: "100%" }} disabled={f.writable === false} />
              )}
            </Form.Item>
          )
        )}
      </Form>
    </Card>
  );

  const renderCalibration = () => (
    <Card title="车架绑定与校准">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        <div>
          <div className="preview-box">
            {connected ? (
              <img
                key={previewKey}
                src={`${api.mjpegUrl()}?t=${previewKey}`}
                alt="实时预览"
              />
            ) : (
              <Text type="secondary">
                <CameraOutlined /> 连接设备后显示实时预览
              </Text>
            )}
          </div>
        </div>
        <div>
          <Badge status="success" text="OK" />
          <Form layout="vertical" style={{ marginTop: 12 }}>
            <Form.Item label="车架号">
              <Input
                placeholder="输入车架号"
                value={frameNo}
                onChange={(e) => setFrameNo(e.target.value)}
              />
            </Form.Item>
          </Form>
          <Space wrap>
            <Button type="primary" icon={<ScanOutlined />} onClick={captureOnce} disabled={!connected}>
              单次扫码
            </Button>
            <Button
              icon={<PlayCircleOutlined />}
              onClick={() => setContinuous(true)}
              disabled={!connected || continuous}
            >
              连续扫码
            </Button>
            <Button icon={<StopOutlined />} onClick={() => setContinuous(false)} disabled={!continuous}>
              停止
            </Button>
          </Space>
          <div className="delta-grid">
            <div className="delta-item">
              <div className="label">delta x</div>
              <div className="value">{currentScan?.x_offset ?? "-"}</div>
            </div>
            <div className="delta-item">
              <div className="label">delta y</div>
              <div className="value">{currentScan?.y_offset ?? "-"}</div>
            </div>
            <div className="delta-item">
              <div className="label">delta θ</div>
              <div className="value">
                {currentScan ? `${currentScan.theta_deg.toFixed(1)}°` : "-"}
              </div>
            </div>
          </div>
          <Text type="secondary">DataMatrix</Text>
          <Input.TextArea
            rows={2}
            readOnly
            value={currentScan?.code ?? ""}
            style={{ marginTop: 8 }}
          />
          <Button
            type="primary"
            block
            size="large"
            style={{ marginTop: 16 }}
            disabled={!connected || !currentScan}
            onClick={() => currentScan && addRecord(currentScan)}
          >
            绑定当前校准结果
          </Button>
        </div>
      </div>
    </Card>
  );

  const renderRecords = () => (
    <Card
      title="校准记录"
      extra={
        <Input
          placeholder="搜索车架号"
          value={searchFrame}
          onChange={(e) => setSearchFrame(e.target.value)}
          style={{ width: 200 }}
          allowClear
        />
      }
    >
      <Table
        size="small"
        dataSource={filteredRecords}
        rowKey="key"
        pagination={{ pageSize: 8 }}
        columns={[
          { title: "时间", dataIndex: "time", key: "time" },
          { title: "车架号", dataIndex: "frameNo", key: "frameNo" },
          { title: "DATAMATRIX", dataIndex: "datamatrix", key: "dm", ellipsis: true },
          { title: "DELTA X", dataIndex: "deltaX", key: "dx" },
          { title: "DELTA Y", dataIndex: "deltaY", key: "dy" },
          { title: "DELTA θ", dataIndex: "deltaTheta", key: "dt" },
          {
            title: "状态",
            dataIndex: "status",
            key: "status",
            render: (s: string) => <Tag color="success">{s}</Tag>,
          },
        ]}
      />
    </Card>
  );

  const renderLogs = () => (
    <Card
      title="操作日志"
      extra={
        <Button
          icon={<ClearOutlined />}
          onClick={async () => {
            await api.clearLogs();
            setLogs([]);
          }}
        >
          清空
        </Button>
      }
    >
      <div
        style={{
          maxHeight: 200,
          overflow: "auto",
          fontFamily: "monospace",
          fontSize: 12,
          background: "#fafafa",
          padding: 12,
          borderRadius: 8,
        }}
      >
        {logs.length === 0 ? (
          <Text type="secondary">暂无日志</Text>
        ) : (
          logs.map((l, i) => (
            <div key={`${l.ts}-${i}`}>
              [{formatTime(l.ts)}] [{l.level}] {l.message}
            </div>
          ))
        )}
      </div>
    </Card>
  );

  return (
    <Layout className="app-layout">
      <Sider width={200} className="app-sider">
        <div className="logo">
          AntDM 校准
          <small>{device?.model_name || "MV-R3138MG010"}</small>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[menuKey]}
          items={menuItems}
          onClick={({ key }) => setMenuKey(key)}
        />
      </Sider>
      <Layout>
        <Content className="app-content">
          <div className="page-header">
            <Title level={3} style={{ margin: 0 }}>
              DataMatrix 定位校准台
            </Title>
            <Space>
              <Button icon={<DownloadOutlined />} onClick={exportCsv}>
                导出 CSV
              </Button>
              <Button type="primary" icon={<ScanOutlined />} onClick={captureOnce} disabled={!connected}>
                单次扫码
              </Button>
            </Space>
          </div>

          {(menuKey === "device" || menuKey === "calibration") && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
              {renderDeviceCard()}
              {renderConfigCard()}
            </div>
          )}

          {menuKey === "config" && (
            <div style={{ marginBottom: 16, maxWidth: 480 }}>{renderConfigCard()}</div>
          )}

          {menuKey === "device" && (
            <div style={{ marginBottom: 16, maxWidth: 640 }}>{renderDeviceCard()}</div>
          )}

          {(menuKey === "calibration" || menuKey === "device") && (
            <div style={{ marginBottom: 16 }}>{renderCalibration()}</div>
          )}

          {menuKey === "records" && <div style={{ marginBottom: 16 }}>{renderRecords()}</div>}

          {(menuKey === "calibration" || menuKey === "records") && renderLogs()}
        </Content>
      </Layout>
    </Layout>
  );
}
