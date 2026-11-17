import { CheckCircle2, CircleDashed, PlayCircle } from "lucide-react";
import { useCallback, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  type AccountSummary,
  type FeasibilityReport,
  type ProfileValues,
  type RiskOverview,
} from "../api/client";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Field } from "../components/ui/Field";
import { EmptyState, ErrorState, LoadingState } from "../components/ui/StateView";
import { usePolling } from "../hooks/usePolling";
import vi from "../i18n/vi";
import { EMPTY, formatDateTime } from "../lib/format";

/* GĐ5 bước 8c (DSH-05, thiết kế 37 mục 4). Số tiền / tỷ lệ đến từ API dạng chuỗi Decimal: trang chỉ
 * đổi cách viết (dịch dấu thập phân), KHÔNG đổi sang số thực để tính lại. Backend kiểm hợp lệ cứng. */

/** Dời dấu thập phân của chuỗi số `k` chữ số (k > 0: × 10^k) — chính xác, không qua số thực. */
export function shiftDecimal(s: string, k: number): string {
  const neg = s.startsWith("-");
  const [i, f = ""] = (neg ? s.slice(1) : s).split(".");
  let digits = i + f;
  let point = i.length + k;
  if (point < 0) {
    digits = "0".repeat(-point) + digits;
    point = 0;
  }
  if (point > digits.length) digits = digits + "0".repeat(point - digits.length);
  let int = digits.slice(0, point).replace(/^0+(?=\d)/, "") || "0";
  let frac = digits.slice(point).replace(/0+$/, "");
  if (int === "") int = "0";
  frac = frac || "";
  return (neg && (int !== "0" || frac) ? "-" : "") + int + (frac ? `.${frac}` : "");
}

/** "0.0025" → "0,25" (phần trăm, cách viết Việt Nam). */
export function pct(fraction: string | null | undefined): string {
  return fraction == null ? EMPTY : shiftDecimal(fraction, 2).replace(".", ",");
}

/** Viết số Decimal kiểu Việt Nam (dấu phẩy thập phân), bỏ số 0 thừa ở cuối. */
export function num(s: string | null | undefined): string {
  return s == null ? EMPTY : shiftDecimal(s, 0).replace(".", ",");
}

/** Mã lý do (vd. RISK_FLAGS:EVENT_WINDOW) → tiếng Việt; mã lạ hiện nguyên mã. */
export function reasonText(code: string): string {
  const [head, ...rest] = code.split(":");
  const map = vi.riskReasons as Record<string, string>;
  const text = map[head];
  if (!text) return code;
  return rest.length ? `${text} (${rest.join(":")})` : text;
}

// Các số người dùng đã chốt 16/11 (H1–H11, nhật ký GĐ5) — chỉ để điền sẵn khi chưa có hồ sơ.
const USER_H1_H11: ProfileValues = {
  risk_per_trade: "0.0025", min_reward_risk: "1.5", max_open_risk: "0.005",
  max_daily_loss: "0.0075", max_weekly_loss: "0.015", max_monthly_loss: "0.03",
  max_consecutive_losses: 5, day_reset_tz: "America/New_York", day_reset_time: "17:00",
  max_trades_per_day: 4, max_drawdown_halt: "0.05", news_hold_policy: "KEEP_SAFE_ONLY",
  weekend_policy: "CLOSE_ALL", weekend_close_before_min: 30, max_effective_leverage: "3",
  cash_flow_policy: "SEPARATE", pyramiding_policy: "ONLY_IF_ALL_IN_PROFIT", notes: "",
};

const PCT_FIELDS = ["risk_per_trade", "max_open_risk", "max_daily_loss", "max_weekly_loss",
  "max_monthly_loss", "max_drawdown_halt"] as const;
const NUM_FIELDS = ["min_reward_risk", "max_effective_leverage"] as const;
const INT_FIELDS = ["max_consecutive_losses", "max_trades_per_day", "weekend_close_before_min"] as const;

export function RiskPage({ account }: { account: AccountSummary | null }) {
  const { t } = useTranslation();
  if (!account) {
    return (
      <div className="page">
        <Card>
          <EmptyState title={t("accounts.noneTitle")} description={t("accounts.noneDesc")} />
        </Card>
      </div>
    );
  }
  return <RiskBody id={account.account_id} />;
}

function RiskBody({ id }: { id: string }) {
  const { t } = useTranslation();
  const fetcher = useCallback(() => api.riskOverview(id), [id]);
  const ov = usePolling<RiskOverview>(fetcher, 15_000, 60_000);
  const d = ov.data;
  const refresh = () => void ov.refresh();
  return (
    <div className="page" id="risk">
      <div className="page__head">
        <div>
          <h1 className="page__title">{t("riskPage.title")}</h1>
          <p className="page__subtitle">{t("riskPage.subtitle")}</p>
        </div>
      </div>
      {!d && ov.loading && <LoadingState label={t("auth.loading")} />}
      {!d && !ov.loading && (
        <ErrorState title={t("riskPage.loadError")} retryLabel={t("overview.retry")} onRetry={refresh} />
      )}
      {d && (
        <>
          {d.is_sample && (
            <div className="banner banner--warning" role="note">
              <span className="banner__body">{t("riskPage.sample")}</span>
            </div>
          )}
          <Readiness d={d} />
          <ProfileCard id={id} d={d} onSaved={refresh} />
          <CommissionCard id={id} d={d} onSaved={refresh} />
          <PaperCard id={id} d={d} onSaved={refresh} />
          <UsageCard d={d} />
          <FeasibilityCard id={id} />
          <ActivityCard d={d} />
        </>
      )}
    </div>
  );
}

function Readiness({ d }: { d: RiskOverview }) {
  const { t } = useTranslation();
  const items: [boolean, string][] = [
    [d.readiness.profile, t("riskPage.readyProfile")],
    [d.readiness.commission, t("riskPage.readyCommission")],
    [d.readiness.paper_started, t("riskPage.readyPaper")],
  ];
  return (
    <Card title={t("riskPage.readiness")} description={t("riskPage.readinessDesc")} labelledBy="risk-ready">
      <ul className="plain-list">
        {items.map(([ok, label]) => (
          <li key={label} className={ok ? "tone-profit" : "tone-gold"}>
            {ok ? <CheckCircle2 size={14} aria-hidden="true" /> : <CircleDashed size={14} aria-hidden="true" />}{" "}
            {label}: {ok ? t("riskPage.done") : t("riskPage.todo")}
          </li>
        ))}
      </ul>
      {!d.strategy_enabled && <p className="tone-gold">{t("riskPage.strategyOff")}</p>}
    </Card>
  );
}

function ProfileCard({ id, d, onSaved }: { id: string; d: RiskOverview; onSaved: () => void }) {
  const { t } = useTranslation();
  const cur = d.profile?.values ?? null;
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  function open() {
    const v = cur ?? USER_H1_H11;
    const f: Record<string, string> = {};
    for (const k of PCT_FIELDS) f[k] = shiftDecimal(String(v[k]), 2);
    for (const k of NUM_FIELDS) f[k] = shiftDecimal(String(v[k]), 0);
    for (const k of INT_FIELDS) f[k] = String(v[k]);
    f.news_hold_policy = v.news_hold_policy;
    f.pyramiding_policy = v.pyramiding_policy;
    setForm(f);
    setError(false);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    const base = cur ?? USER_H1_H11;
    const values: ProfileValues = { ...base };
    const rec = values as unknown as Record<string, string | number>;
    for (const k of PCT_FIELDS) rec[k] = shiftDecimal(form[k].replace(",", ".").trim(), -2);
    for (const k of NUM_FIELDS) rec[k] = form[k].replace(",", ".").trim();
    for (const k of INT_FIELDS) rec[k] = Number.parseInt(form[k], 10);
    values.news_hold_policy = form.news_hold_policy;
    values.pyramiding_policy = form.pyramiding_policy;
    setBusy(true);
    setError(false);
    try {
      await api.createProfile(id, values, reason);
      setForm(null);
      setReason("");
      onSaved();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  const label = (k: string) => t(`riskPage.fields.${k}` as "riskPage.fields.risk_per_trade");
  const hint = (k: string) => (vi.riskPage.hints as Record<string, string>)[k];
  return (
    <Card title={t("riskPage.profile")} description={t("riskPage.profileDesc")} labelledBy="risk-profile">
      {!cur && <p className="tone-loss">{t("riskPage.noProfile")}</p>}
      {cur && d.profile && (
        <>
          <dl className="kv">
            {PCT_FIELDS.map((k) => (
              <div key={k}><dt>{label(k)}</dt><dd>{pct(String(cur[k]))} %</dd></div>
            ))}
            {NUM_FIELDS.map((k) => (
              <div key={k}><dt>{label(k)}</dt><dd>{num(String(cur[k]))}</dd></div>
            ))}
            {INT_FIELDS.map((k) => (
              <div key={k}><dt>{label(k)}</dt><dd>{cur[k]}</dd></div>
            ))}
            <div><dt>{label("news_hold_policy")}</dt><dd>{policy(cur.news_hold_policy)}</dd></div>
            <div><dt>{label("pyramiding_policy")}</dt><dd>{policy(cur.pyramiding_policy)}</dd></div>
            <div><dt>{label("day_reset")}</dt><dd>{cur.day_reset_time} ({cur.day_reset_tz})</dd></div>
          </dl>
          <ul className="plain-list">
            {d.profile_history.map((p) => (
              <li key={p.version} className="header__label">
                {t("riskPage.version", { v: p.version, time: formatDateTime(p.created_at), reason: p.reason })}
              </li>
            ))}
          </ul>
        </>
      )}
      {!form && (
        <Button variant={cur ? "secondary" : "primary"} onClick={open}>
          {t("riskPage.newVersion")}
        </Button>
      )}
      {form && (
        <form onSubmit={(e) => void submit(e)} aria-label={t("riskPage.newVersion")}>
          {!cur && <p className="header__label">{t("riskPage.prefillH")}</p>}
          {[...PCT_FIELDS, ...NUM_FIELDS, ...INT_FIELDS].map((k) => (
            <Field key={k} label={label(k)} hint={hint(k)} value={form[k]} inputMode="decimal" required
              onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
          ))}
          <PolicySelect label={label("news_hold_policy")} value={form.news_hold_policy}
            options={["KEEP_SAFE_ONLY", "CLOSE_ALL"]}
            onChange={(v) => setForm({ ...form, news_hold_policy: v })} />
          <PolicySelect label={label("pyramiding_policy")} value={form.pyramiding_policy}
            options={["ONLY_IF_ALL_IN_PROFIT", "ONLY_IF_ALL_SAFE", "NONE"]}
            onChange={(v) => setForm({ ...form, pyramiding_policy: v })} />
          <Field label={t("riskPage.reason")} value={reason} required maxLength={256}
            onChange={(e) => setReason(e.target.value)} />
          {error && (
            <div className="banner banner--error" role="alert"><span className="banner__body">{t("riskPage.profileError")}</span></div>
          )}
          <div className="row-actions">
            <Button type="submit" variant="primary" disabled={busy || !reason.trim()}>{t("riskPage.save")}</Button>
            <Button onClick={() => setForm(null)}>{t("riskPage.cancel")}</Button>
          </div>
        </form>
      )}
    </Card>
  );
}

function policy(v: string): string {
  return (vi.riskPage.policies as Record<string, string>)[v] ?? v;
}

function PolicySelect({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void;
}) {
  return (
    <div className="field">
      <label className="field__label">
        {label}
        <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
          {options.map((o) => <option key={o} value={o}>{policy(o)}</option>)}
        </select>
      </label>
    </div>
  );
}

function CommissionCard({ id, d, onSaved }: { id: string; d: RiskOverview; onSaved: () => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(false);
    try {
      await api.setCommission(id, value.replace(",", ".").trim(), reason);
      setValue("");
      setReason("");
      onSaved();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  const c = d.commission;
  return (
    <Card title={t("riskPage.commission")} description={t("riskPage.commissionDesc")} labelledBy="risk-commission">
      {c ? (
        <p>{t("riskPage.commissionNow", { v: num(String(c.per_lot)), time: formatDateTime(c.created_at) })}</p>
      ) : (
        <p className="tone-loss">{t("riskPage.noCommission")}</p>
      )}
      <form onSubmit={(e) => void submit(e)} aria-label={t("riskPage.commission")}>
        <Field label={t("riskPage.perLot")} value={value} inputMode="decimal" required
          onChange={(e) => setValue(e.target.value)} />
        <Field label={t("riskPage.reason")} value={reason} required maxLength={256}
          onChange={(e) => setReason(e.target.value)} />
        {error && (
          <div className="banner banner--error" role="alert"><span className="banner__body">{t("riskPage.commissionError")}</span></div>
        )}
        <Button type="submit" variant="primary" disabled={busy || !value.trim() || !reason.trim()}>
          {t("riskPage.save")}
        </Button>
      </form>
    </Card>
  );
}

function PaperCard({ id, d, onSaved }: { id: string; d: RiskOverview; onSaved: () => void }) {
  const { t } = useTranslation();
  const p = d.paper;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [amount, setAmount] = useState("");
  const [cashReason, setCashReason] = useState("");
  const [resetReason, setResetReason] = useState("");
  const [confirm, setConfirm] = useState(false);

  async function run(fn: () => Promise<unknown>, msg: string) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onSaved();
      return true;
    } catch {
      setError(msg);
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={t("riskPage.paper")} description={t("riskPage.paperDesc")} labelledBy="risk-paper">
      {error && (
        <div className="banner banner--error" role="alert"><span className="banner__body">{error}</span></div>
      )}
      {!p.started ? (
        <>
          <p>{t("riskPage.paperNotStarted")}</p>
          <Button variant="primary" icon={<PlayCircle size={14} aria-hidden="true" />} disabled={busy}
            onClick={() => void run(() => api.startPaper(id, "Bắt đầu sổ paper từ trang Rủi ro"),
              t("riskPage.startError"))}>
            {t("riskPage.startPaper")}
          </Button>
        </>
      ) : (
        <>
          <dl className="kv">
            <div><dt>{t("riskPage.capital")}</dt><dd>{num(p.capital as string)} USD</dd></div>
            <div><dt>{t("riskPage.realized")}</dt><dd>{num(p.realized_equity as string)} USD</dd></div>
            <div><dt>{t("riskPage.unrealized")}</dt><dd>{p.unrealized == null ? EMPTY : `${num(p.unrealized as string)} USD`}</dd></div>
            <div><dt>{t("riskPage.peak")}</dt><dd>{num(p.peak as string)} USD</dd></div>
            <div><dt>{t("riskPage.drawdown")}</dt><dd>{pct(p.drawdown as string)} %</dd></div>
          </dl>
          {p.halted && (
            <div className="banner banner--error" role="alert">
              <span className="banner__body">{t("riskPage.halted")}</span>
            </div>
          )}
          {p.halted && (
            <form aria-label={t("riskPage.resetTitle")} onSubmit={(e) => {
              e.preventDefault();
              void run(() => api.drawdownReset(id, resetReason), t("riskPage.cashError"));
            }}>
              <h3 className="card__title">{t("riskPage.resetTitle")}</h3>
              <label className="field__label">
                <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />{" "}
                {t("riskPage.resetConfirm")}
              </label>
              <Field label={t("riskPage.reason")} value={resetReason} required maxLength={256}
                onChange={(e) => setResetReason(e.target.value)} />
              <Button type="submit" variant="danger" disabled={busy || !confirm || !resetReason.trim()}>
                {t("riskPage.resetButton")}
              </Button>
            </form>
          )}
          <form aria-label={t("riskPage.cash")} onSubmit={(e) => e.preventDefault()}>
            <h3 className="card__title">{t("riskPage.cash")}</h3>
            <Field label={t("riskPage.amount")} value={amount} inputMode="decimal" required
              onChange={(e) => setAmount(e.target.value)} />
            <Field label={t("riskPage.reason")} value={cashReason} required maxLength={256}
              onChange={(e) => setCashReason(e.target.value)} />
            <div className="row-actions">
              {(["CASH_IN", "CASH_OUT"] as const).map((k) => (
                <Button key={k} disabled={busy || !amount.trim() || !cashReason.trim()}
                  onClick={() => void run(() => api.paperCash(id, k, amount.replace(",", ".").trim(), cashReason),
                    t("riskPage.cashError")).then((ok) => ok && setAmount(""))}>
                  {k === "CASH_IN" ? t("riskPage.cashIn") : t("riskPage.cashOut")}
                </Button>
              ))}
            </div>
          </form>
        </>
      )}
      <h3 className="card__title">{t("riskPage.positions")}</h3>
      {p.positions.length === 0 ? (
        <p className="header__label">{t("riskPage.noPositions")}</p>
      ) : (
        <ul className="plain-list">
          {p.positions.map((x) => (
            <li key={x.position_id}>
              {x.side} {num(x.volume as string)} lot @ {num(x.entry_price as string)} · SL {num(x.stop_loss as string)}
              {x.take_profit ? ` · TP ${num(x.take_profit as string)}` : ""} · {formatDateTime(x.opened_at)}
            </li>
          ))}
        </ul>
      )}
      <p className="header__label">{t("riskPage.reservations", { n: p.reservations.length })}</p>
    </Card>
  );
}

function UsageCard({ d }: { d: RiskOverview }) {
  const { t } = useTranslation();
  const u = d.usage;
  return (
    <Card title={t("riskPage.usage")} description={t("riskPage.usageDesc")} labelledBy="risk-usage">
      {!u ? (
        <p className="header__label">{t("riskPage.noUsage")}</p>
      ) : (
        <dl className="kv">
          <div><dt>{t("riskPage.tradesToday")}</dt><dd>{t("riskPage.of", { a: u.trades_today, b: u.max_trades_per_day })}</dd></div>
          <div><dt>{t("riskPage.lossDay")}</dt><dd>{pct(u.daily_loss as string | null)} % / {pct(u.max_daily_loss as string)} %</dd></div>
          <div><dt>{t("riskPage.lossWeek")}</dt><dd>{pct(u.weekly_loss as string | null)} % / {pct(u.max_weekly_loss as string)} %</dd></div>
          <div><dt>{t("riskPage.lossMonth")}</dt><dd>{pct(u.monthly_loss as string | null)} % / {pct(u.max_monthly_loss as string)} %</dd></div>
          <div><dt>{t("riskPage.streak")}</dt><dd>{t("riskPage.of", { a: u.loss_streak, b: u.max_consecutive_losses })}</dd></div>
        </dl>
      )}
    </Card>
  );
}

function FeasibilityCard({ id }: { id: string }) {
  const { t } = useTranslation();
  const fetcher = useCallback(() => api.feasibility(id), [id]);
  const r = usePolling<FeasibilityReport>(fetcher, 60_000, 300_000).data;
  return (
    <Card title={t("riskPage.feasibility")} description={t("riskPage.feasibilityDesc")} labelledBy="risk-feas">
      {!r ? (
        <LoadingState label={t("auth.loading")} />
      ) : (
        <>
          {r.label && <p className="tone-gold"><strong>{r.label}</strong></p>}
          {r.missing.length > 0 ? (
            <p className="tone-loss">{t("riskPage.notEnough", { list: r.missing.map(reasonText).join(", ") })}</p>
          ) : (
            <>
              <ul className="plain-list">
                {r.levels.map((lv) => {
                  const p = pct(lv.risk_fraction as string);
                  return (
                    <li key={String(lv.risk_fraction)}
                      className={lv.verdict === "KHA_THI" ? "tone-profit" : lv.verdict === "KHONG_KHA_THI" ? "tone-loss" : "tone-gold"}>
                      {lv.verdict === "KHA_THI"
                        ? t("riskPage.feasible", { pct: `${p} %`, lots: num(lv.lots as string), risk: num(lv.risk_amount as string) })
                        : lv.verdict === "KHONG_KHA_THI"
                          ? t("riskPage.notFeasible", { pct: `${p} %`, short: num(lv.shortfall as string), min: num(lv.min_equity as string) })
                          : t("riskPage.illustrative", { pct: `${p} %`, lots: num(lv.lots as string) })}
                    </li>
                  );
                })}
              </ul>
              <dl className="kv">
                <div><dt>{t("riskPage.atr")}</dt><dd>{num(r.atr as string)}</dd></div>
                <div><dt>{t("riskPage.riskPerLot")}</dt><dd>{num(r.risk_per_lot as string)} USD</dd></div>
                <div><dt>{t("riskPage.rr")}</dt><dd>{num(r.reward_risk as string)}</dd></div>
              </dl>
              <p className="header__label">
                {t("riskPage.minLot", { lot: num(r.min_lot as string), risk: num(r.min_lot_risk as string), pct: num(r.min_lot_risk_pct as string) })}
                {" · "}
                {t("riskPage.slTp", { sl: num(r.sl_distance as string), tp: num(r.tp_distance as string) })}
              </p>
              {r.warnings.map((w) => <p key={w} className="tone-gold">{w}</p>)}
            </>
          )}
        </>
      )}
    </Card>
  );
}

function ActivityCard({ d }: { d: RiskOverview }) {
  const { t } = useTranslation();
  const out = (o: string) => (vi.riskPage.outcome as Record<string, string>)[o] ?? o;
  return (
    <Card title={t("riskPage.activity")} labelledBy="risk-activity">
      <h3 className="card__title">{t("riskPage.decisions")}</h3>
      {d.decisions.length === 0 ? <p className="header__label">{t("riskPage.noActivity")}</p> : (
        <ul className="plain-list">
          {d.decisions.map((x) => (
            <li key={x.risk_decision_id}>
              {formatDateTime(x.decided_at)} · {out(x.outcome)}
              {x.outcome !== "REJECTED" && ` · ${num(x.volume as string)} lot`}
              {x.reason_codes.length > 0 && ` · ${x.reason_codes.map(reasonText).join(", ")}`}
            </li>
          ))}
        </ul>
      )}
      <h3 className="card__title">{t("riskPage.evaluations")}</h3>
      {d.evaluations.length === 0 ? <p className="header__label">{t("riskPage.noActivity")}</p> : (
        <ul className="plain-list">
          {d.evaluations.map((x) => (
            <li key={`${x.market_view_id}-${x.evaluated_at}`}>
              {formatDateTime(x.evaluated_at)} · {out(x.outcome)}
              {x.risk_outcome && ` → ${out(x.risk_outcome)}`}
              {x.reasons.length > 0 && ` · ${x.reasons.map(reasonText).join(", ")}`}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
