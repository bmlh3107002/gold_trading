import { useCallback, useEffect, useState } from "react";
import { api, type SafetyCommand, type SystemStatus, type TradingMode } from "./api/client";

const MODES: TradingMode[] = ["BACKTEST", "PAPER", "SHADOW", "LIVE"];
const POLL_MS = 3000;

export default function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actor, setActor] = useState("operator");
  const [reason, setReason] = useState("");

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.status());
      setError(null);
    } catch (e) {
      setError(`Không kết nối được backend: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  async function run(fn: () => Promise<SystemStatus>) {
    try {
      setStatus(await fn());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function safety(action: SafetyCommand["action"]) {
    const reason_code = reason.trim() || `MANUAL_${action.toUpperCase()}`;
    let operator_approved = false;
    if (action === "resume" && status?.safety_state === "HALTED") {
      operator_approved = window.confirm(
        "Hệ thống đang HALTED. Bạn xác nhận đã kiểm tra nguyên nhân và cho phép mở lệnh lại?",
      );
      if (!operator_approved) return;
    }
    run(() => api.safety({ action, reason_code, actor, operator_approved }));
  }

  return (
    <main>
      <header>
        <h1>Gold Trading Dashboard</h1>
        {status && <span className="muted">backend v{status.version}</span>}
      </header>

      {error && <div className="alert">{error}</div>}

      {status && (
        <>
          <section className="grid">
            <div className="card">
              <h2>Safety</h2>
              <div className={`badge state-${status.safety_state}`}>{status.safety_state}</div>
              <p className="muted">
                {status.allows_new_orders ? "Được mở lệnh mới" : "Đang chặn lệnh mới"}
              </p>
            </div>
            <div className="card">
              <h2>Mode</h2>
              <div className="badge">{status.mode}</div>
              <p className="muted">LIVE {status.live_unlocked ? "đã mở khóa" : "đang khóa"}</p>
            </div>
            <div className="card">
              <h2>MarketView</h2>
              {status.market_view ? (
                <>
                  <div className="badge">{status.market_view.bias}</div>
                  <p className="muted">
                    confidence {status.market_view.confidence.toFixed(2)} ·{" "}
                    {status.market_view.regime}
                  </p>
                </>
              ) : (
                <p className="muted">Chưa có MarketView hợp lệ</p>
              )}
            </div>
          </section>

          <section className="card">
            <h2>Điều khiển</h2>
            <div className="row">
              <label>
                Người thao tác
                <input value={actor} onChange={(e) => setActor(e.target.value)} />
              </label>
              <label>
                Reason code
                <input
                  value={reason}
                  placeholder="VD: NEWS_SHOCK"
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            </div>
            <div className="row">
              <button onClick={() => safety("resume")}>Resume (ACTIVE)</button>
              <button onClick={() => safety("pause")}>Pause</button>
              <button className="danger" onClick={() => safety("halt")}>
                Kill switch (HALT)
              </button>
            </div>
            <div className="row">
              {MODES.map((m) => (
                <button
                  key={m}
                  disabled={m === status.mode}
                  onClick={() => run(() => api.mode({ mode: m, actor, checklist: {} }))}
                >
                  {m}
                </button>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>Lịch sử Safety</h2>
            {status.safety_history.length === 0 ? (
              <p className="muted">Chưa có chuyển trạng thái</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Thời gian</th>
                      <th>Từ → Đến</th>
                      <th>Lý do</th>
                      <th>Nguồn / Người</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...status.safety_history].reverse().map((t) => (
                      <tr key={t.transition_id}>
                        <td>{new Date(t.at).toLocaleString()}</td>
                        <td>
                          {t.from_state} → {t.to_state}
                        </td>
                        <td>{t.reason_code}</td>
                        <td>
                          {t.trigger_source} / {t.actor}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
