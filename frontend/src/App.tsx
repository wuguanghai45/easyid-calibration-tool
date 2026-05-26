import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import {
  normalizeThetaOffsetDeg,
  runRealCalibration,
  type UiState,
} from "./calibration";

const IDLE_HINT = "输入车架号后开始标定。";

export default function App() {
  const [vin, setVin] = useState("");
  const [uiState, setUiState] = useState<UiState>("idle");
  const [resultText, setResultText] = useState("待开始");
  const [steps, setSteps] = useState<string[]>([]);
  const [hint, setHint] = useState(IDLE_HINT);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.body.className = uiState;
  }, [uiState]);

  const resetProgress = useCallback(() => {
    setSteps([]);
    setHint("");
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

    const frameNo = vin.trim();

    try {
      const outcome = await runRealCalibration();

      setSteps(outcome.steps);

      if (outcome.ok) {
        setUiState("success");
        setResultText("成功");

        const feishuRes = await api.syncCameraOffset(
          frameNo,
          normalizeThetaOffsetDeg(outcome.scan.theta_deg)
        );
        const nextSteps = [...outcome.steps];
        let hintText = outcome.hint;
        if (feishuRes.ok) {
          nextSteps.push("飞书同步成功");
        } else {
          hintText = `${outcome.hint} 飞书同步失败：${feishuRes.error || "未知错误"}`;
        }
        setSteps(nextSteps);
        setHint(hintText);

        try {
          sessionStorage.setItem(
            "last_calibration",
            JSON.stringify({
              vin: frameNo,
              scan: outcome.scan,
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
        setHint(outcome.hint);
      }
    } catch (err) {
      setUiState("failure");
      setResultText("失败");
      setHint(`流程异常：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main>
      <h1>相机外参标定</h1>

      <label htmlFor="vin">车架号</label>
      <input
        id="vin"
        type="text"
        autoComplete="off"
        placeholder="请输入车架号"
        value={vin}
        disabled={busy}
        onChange={(e) => setVin(e.target.value)}
      />

      <button type="button" disabled={busy} onClick={runCalibration}>
        开始标定
      </button>

      <section className="status" aria-live="polite">
        <p className="result">{resultText}</p>
        <ul>
          {steps.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
        <p className="hint">{hint || (uiState === "idle" ? IDLE_HINT : "")}</p>
      </section>
    </main>
  );
}
