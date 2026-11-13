import { Database } from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { api, type DataSource } from "../api/client";
import { Badge, type BadgeTone } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { EmptyState, LoadingState } from "../components/ui/StateView";
import { usePolling } from "../hooks/usePolling";
import { formatDateTime, formatNumber } from "../lib/format";

const STATUS_TONE: Record<DataSource["status"], BadgeTone> = {
  HEALTHY: "profit",
  STALE: "gold",
  MISSING: "loss",
  INVALID: "loss",
};

const KNOWN_NAMES = new Set([
  "fed_fomc", "bea_schedule", "bea_nipa", "dol_claims_schedule", "dol_claims", "fed_h15",
  "cftc_cot_gold", "fed_rss_monetary", "fed_rss_speeches", "treasury_press", "bls_schedule",
  "bls_values",
]);
const KNOWN_REASONS = new Set([
  "OK", "FETCH_TTL_EXPIRED", "DATA_TTL_EXPIRED", "NEVER_CHECKED", "NEVER_OK", "NO_DATA", "DISABLED",
  "UNKNOWN_SOURCE", "AUTH_FAILED", "KEY_MISSING", "KEY_INVALID", "FORBIDDEN", "SOURCE_DISCONTINUED",
  "ALL_RECORDS_REJECTED", "PARSE_ERROR", "SCHEDULE_TABLE_EXPIRING",
]);

/** Tên dễ đọc; nguồn mới chưa có bản dịch → hiện nguyên mã (không vỡ trang). */
function sourceName(t: TFunction, name: string): string {
  return KNOWN_NAMES.has(name) ? t(`sources.name.${name as "fed_h15"}`) : name;
}

function reasonLabel(t: TFunction, reason: string): string {
  return KNOWN_REASONS.has(reason) ? t(`sources.reason.${reason as "OK"}`) : reason;
}

/** Khoảng thời gian dạng "5 phút", "3 giờ", "2 ngày" (làm tròn xuống). */
export function formatAge(
  seconds: number | null | undefined,
  t: (k: "sources.age.seconds" | "sources.age.minutes" | "sources.age.hours" | "sources.age.days", o: { n: number }) => string,
): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return t("sources.age.seconds", { n: seconds });
  if (seconds < 3600) return t("sources.age.minutes", { n: Math.floor(seconds / 60) });
  if (seconds < 172800) return t("sources.age.hours", { n: Math.floor(seconds / 3600) });
  return t("sources.age.days", { n: Math.floor(seconds / 86400) });
}

/** DSH-09: trạng thái từng nguồn dữ liệu ngoài (lịch, số vĩ mô, vị thế, tin). Chỉ đọc. */
export function SourcesPage() {
  const { t } = useTranslation();
  const res = usePolling(api.dataSources, 30_000, 120_000);
  const d = res.data;
  return (
    <div className="page" id="sources">
      <div className="page__head">
        <div>
          <h1 className="page__title">{t("sources.title")}</h1>
          <p className="page__subtitle">{t("sources.subtitle")}</p>
        </div>
      </div>
      <Card title={t("sources.tableTitle")} description={d ? t("sources.asOf", { time: formatDateTime(d.as_of) }) : undefined} labelledBy="sources-title">
        {!d ? (
          <LoadingState label={t("market.loading")} />
        ) : !d.runner_enabled || d.sources.length === 0 ? (
          <EmptyState icon={<Database size={20} />} title={t("sources.offTitle")} description={t("sources.offDesc")} />
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label={t("sources.tableTitle")}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("sources.col.name")}</th>
                  <th scope="col">{t("sources.col.status")}</th>
                  <th scope="col">{t("sources.col.lastOk")}</th>
                  <th scope="col">{t("sources.col.dataAge")}</th>
                  <th scope="col">{t("sources.col.error")}</th>
                  <th scope="col">{t("sources.col.quarantine", { days: d.quarantine_window_days })}</th>
                </tr>
              </thead>
              <tbody>
                {d.sources.map((s) => (
                  <tr key={s.name}>
                    <td>
                      <div>{sourceName(t, s.name)}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {s.name} · {t(`sources.kind.${s.kind}`)}
                      </div>
                    </td>
                    <td>
                      <Badge tone={STATUS_TONE[s.status]} dot>
                        {t(`sources.status.${s.status}`)}
                      </Badge>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {reasonLabel(t, s.reason)}
                        {s.flags.includes("RECENT_FAILURES") ? ` · ${t("sources.recentFailures", { n: s.failures_since_ok })}` : ""}
                      </div>
                    </td>
                    <td className="num">
                      <div>{formatDateTime(s.last_ok_at)}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {s.receive_age_seconds === null ? "" : t("sources.ago", { age: formatAge(s.receive_age_seconds, t) })}
                      </div>
                    </td>
                    <td className="num">
                      {/* Lịch: sự kiện nằm ở tương lai → "độ trễ dữ liệu" không có nghĩa */}
                      {s.kind === "calendar" ? "—" : formatAge(s.data_age_seconds, t)}
                    </td>
                    <td>{s.last_error_code ?? "—"}</td>
                    <td className={`num ${s.quarantine_7d > 0 ? "tone-loss" : ""}`}>
                      {formatNumber(s.quarantine_7d, 0)}
                      <span className="muted"> / {formatNumber(s.quarantine_total, 0)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>{t("sources.note")}</p>
    </div>
  );
}
