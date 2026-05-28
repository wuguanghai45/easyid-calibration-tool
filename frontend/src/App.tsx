import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import {
  buildFeishuDetail,
  END_STEP_TITLE,
  FEISHU_STEP_LABEL,
  FEISHU_STEP_SHORT_LABEL,
  normalizeThetaOffsetDeg,
  progressCompletedCount,
  runRealCalibration,
  STEP_LABELS,
  STEP_SHORT_LABELS,
  TOTAL_PROGRESS_STEPS,
  type CalibrationProgress,
  type UiState,
} from "./calibration";
import type { FlowStep } from "./types";
import { VinScanDialog } from "./VinScanDialog";
import { isVinScanUiAvailable, normalizeVin } from "./vinScanner";

const IDLE_HINT_HTTP = "输入车架号后开始标定。";
const IDLE_HINT_HTTPS = "输入车架号或点击「扫码」后开始标定。";

const PROGRESS_STEP_LABELS = [...STEP_SHORT_LABELS, FEISHU_STEP_SHORT_LABEL];

type StepVisualStatus = "pending" | "active" | "done";

function stepStatus(
  index: number,
  completedCount: number,
  activeIndex: number | null
): StepVisualStatus {
  if (index < completedCount) return "done";
  if (activeIndex !== null && index === activeIndex) return "active";
  return "pending";
}

function progressPercent(completedCount: number, activeIndex: number | null): number {
  const partial = activeIndex !== null ? 0.5 : 0;
  return Math.min(100, ((completedCount + partial) / TOTAL_PROGRESS_STEPS) * 100);
}

/** Split comma-joined detail string into display rows. */
function splitDetailItems(detail: string): string[] {
  return detail
    .split("，")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Parse "label value" pairs (e.g. "型号 MV-xxx", "IP 192.168.x.x"). */
function parseDetailPair(item: string): { label: string; value: string } {
  const space = item.indexOf(" ");
  if (space <= 0) {
    return { label: "", value: item };
  }
  return { label: item.slice(0, space), value: item.slice(space + 1).trim() };
}

export default function App() {
  const [vin, setVin] = useState("");
  const [uiState, setUiState] = useState<UiState>("idle");
  const [resultText, setResultText] = useState("待开始");
  const [steps, setSteps] = useState<FlowStep[]>([]);
  const [activeStepIndex, setActiveStepIndex] = useState<number | null>(null);
  const showVinScan = isVinScanUiAvailable();
  const idleHint = showVinScan ? IDLE_HINT_HTTPS : IDLE_HINT_HTTP;
  const [hint, setHint] = useState(idleHint);
  const [busy, setBusy] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);

  useEffect(() => {
    document.body.className = uiState;
  }, [uiState]);

  const resetProgress = useCallback(() => {
    setSteps([]);
    setActiveStepIndex(null);
    setHint("");
  }, []);

  const applyProgress = useCallback((progress: CalibrationProgress) => {
    setSteps(progress.completedSteps);
    setActiveStepIndex(progress.activeIndex);
  }, []);

  const runCalibration = async () => {
    if (!vin.trim()) {
      setHint("请先输入车架号。");
      return;
    }

    setBusy(true);
    setVin((v) => v.trim());
    resetProgress();
    setUiState("running");
    setResultText("标定中");
    setActiveStepIndex(0);

    const frameNo = vin.trim();

    try {
      const outcome = await runRealCalibration(applyProgress);

      setSteps(outcome.steps);

      if (outcome.ok) {
        const feishuStepIndex = STEP_LABELS.length;
        setActiveStepIndex(feishuStepIndex);
        setResultText("飞书同步中");

        const feishuRes = await api.syncCameraOffset(
          frameNo,
          normalizeThetaOffsetDeg(outcome.scan.theta_deg)
        );
        const nextSteps = [...outcome.steps];
        let hintText = outcome.hint;
        if (feishuRes.ok) {
          const feishuDetail = buildFeishuDetail(feishuRes);
          nextSteps.push(
            feishuDetail
              ? { id: "feishu", title: FEISHU_STEP_LABEL, detail: feishuDetail }
              : { id: "feishu", title: FEISHU_STEP_LABEL }
          );
          nextSteps.push({ id: "end", title: END_STEP_TITLE });
        } else {
          hintText = `${outcome.hint} 飞书同步失败：${feishuRes.error || "未知错误"}`;
        }
        setSteps(nextSteps);
        setActiveStepIndex(null);
        setUiState("success");
        setResultText("成功");
        setHint(hintText);

        try {
          sessionStorage.setItem(
            "last_calibration",
            JSON.stringify({
              vin: frameNo,
              scan: outcome.scan,
              steps: nextSteps,
              ts: Date.now(),
              status: "OK",
              feishu_synced: feishuRes.ok,
            })
          );
        } catch {
          /* ignore quota / private mode */
        }
      } else {
        setUiState("failure");
        setResultText("失败");
        setActiveStepIndex(null);
        setHint(outcome.hint);
      }
    } catch (err) {
      setUiState("failure");
      setResultText("失败");
      setActiveStepIndex(null);
      setHint(`流程异常：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const completedCount = progressCompletedCount(steps);
  const showProgress = uiState !== "idle";
  const percent = progressPercent(completedCount, activeStepIndex);

  return (
    <main>
      <h1>相机外参标定</h1>

      <label htmlFor="vin">车架号</label>
      <div className="vin-row">
        <input
          id="vin"
          type="text"
          autoComplete="off"
          placeholder="请输入车架号"
          value={vin}
          disabled={busy}
          onChange={(e) => setVin(e.target.value)}
        />
        {showVinScan && (
          <button
            type="button"
            className="vin-scan-btn"
            disabled={busy}
            onClick={() => setScanOpen(true)}
          >
            扫码
          </button>
        )}
      </div>

      {showVinScan && (
        <VinScanDialog
          open={scanOpen}
          onClose={() => setScanOpen(false)}
          onScanned={(value) => {
            setVin(normalizeVin(value));
            setScanOpen(false);
            setHint("已扫码填入车架号。");
          }}
        />
      )}

      <button type="button" disabled={busy} onClick={runCalibration}>
        开始标定
      </button>

      <section className="status" aria-live="polite">
        <p className="result">{resultText}</p>

        {showProgress && (
          <div
            className={`progress-panel${
              uiState === "success" && activeStepIndex === null
                ? " progress-panel--complete"
                : ""
            }`}
            role="group"
            aria-label="标定进度"
          >
            <div
              className="progress-track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(percent)}
              aria-label="流程进度"
            >
              <div className="progress-fill" style={{ width: `${percent}%` }} />
            </div>
            <ol className="progress-steps">
              {PROGRESS_STEP_LABELS.map((label, index) => (
                <li
                  key={label}
                  className={stepStatus(index, completedCount, activeStepIndex)}
                  aria-current={
                    stepStatus(index, completedCount, activeStepIndex) === "active"
                      ? "step"
                      : undefined
                  }
                >
                  <span className="progress-step-marker" aria-hidden="true" />
                  <span className="progress-step-label">{label}</span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {steps.length > 0 && (
          <ul className="flow-steps">
            {steps.map((step) => {
              const isEnd = step.id === "end";
              const meta = step.detail ? splitDetailItems(step.detail) : [];
              return (
                <li
                  key={step.id}
                  className={isEnd ? "flow-step flow-step--end" : "flow-step"}
                >
                  {meta.length > 0 ? (
                    // Native details/summary: chevron beside step title toggles detail panel.
                    <details className="flow-step-detail" open={false}>
                      <summary
                        className="flow-step-header"
                        aria-label={`${step.title} 详细数据`}
                      >
                        <span className="flow-step-title">{step.title}</span>
                        <span className="flow-step-toggle" aria-hidden="true" />
                      </summary>
                      <dl className="flow-step-meta">
                        {meta.map((item) => {
                          const { label, value } = parseDetailPair(item);
                          return (
                            <div key={item} className="flow-step-meta-row">
                              {label ? (
                                <>
                                  <dt>{label}</dt>
                                  <dd>{value}</dd>
                                </>
                              ) : (
                                <dd className="flow-step-meta-single">{value}</dd>
                              )}
                            </div>
                          );
                        })}
                      </dl>
                    </details>
                  ) : (
                    <span className="flow-step-title">{step.title}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <p
          className={`hint${uiState === "success" && hint ? " hint--summary" : ""}`}
        >
          {hint || (uiState === "idle" ? idleHint : "")}
        </p>
      </section>
    </main>
  );
}
