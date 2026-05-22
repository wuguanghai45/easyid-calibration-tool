import { useCallback, useEffect, useState } from "react";
import {
  runMockCalibration,
  runRealCalibration,
  type UiState,
} from "./calibration";

const IDLE_HINT = "输入车架号后开始标定。";

export default function App() {
  const [vin, setVin] = useState("");
  const [simulateFailure, setSimulateFailure] = useState(false);
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

    try {
      const outcome = simulateFailure
        ? await runMockCalibration(2)
        : await runRealCalibration();

      setSteps(outcome.steps);

      if (outcome.ok) {
        setUiState("success");
        setResultText("成功");
        setHint(outcome.hint);
        try {
          sessionStorage.setItem(
            "last_calibration",
            JSON.stringify({
              vin: vin.trim(),
              scan: outcome.scan,
              ts: Date.now(),
              status: "OK",
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

      <label className="demo">
        <input
          type="checkbox"
          checked={simulateFailure}
          disabled={busy}
          onChange={(e) => setSimulateFailure(e.target.checked)}
        />
        模拟失败
      </label>

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
