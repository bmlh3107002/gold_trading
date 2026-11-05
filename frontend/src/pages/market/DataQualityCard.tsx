import { ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { DataQuality } from "../../api/client";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { EmptyState, LoadingState } from "../../components/ui/StateView";
import { formatDateTime, formatNumber } from "../../lib/format";
import { dataSourceLabel, quarantineLabel } from "../../lib/labels";

export function DataQualityCard({ q }: { q: DataQuality | null }) {
  const { t } = useTranslation();
  return (
    <Card title={t("quality.title")} description={t("quality.desc")} labelledBy="quality-title">
      {!q ? (
        <LoadingState label={t("market.loading")} />
      ) : (
        <>
          <div className="kv" style={{ marginBottom: 16 }}>
            <div>
              <div className="kv__label">{t("quality.source")}</div>
              <div className="kv__value">
                {q.source ? (
                  <Badge tone={q.is_sample ? "gold" : "info"}>{dataSourceLabel(t, q.source)}</Badge>
                ) : (
                  "—"
                )}
              </div>
            </div>
            <div>
              <div className="kv__label">{t("quality.count")}</div>
              <div className="kv__value">{formatNumber(q.candle_count, 0)}</div>
            </div>
            <div>
              <div className="kv__label">{t("quality.range")}</div>
              <div className="kv__value">
                {formatDateTime(q.first_open_time)} → {formatDateTime(q.last_open_time)}
              </div>
            </div>
            <div>
              <div className="kv__label">{t("quality.lastIngested")}</div>
              <div className="kv__value">{formatDateTime(q.last_ingested_at)}</div>
            </div>
            <div>
              <div className="kv__label">{t("quality.quarantined")}</div>
              <div className={`kv__value ${q.quarantined > 0 ? "tone-loss" : "tone-profit"}`}>
                {formatNumber(q.quarantined, 0)}
              </div>
            </div>
          </div>
          <div className="control-group__label" style={{ marginBottom: 8 }}>
            {t("quality.recent")}
          </div>
          {q.recent_quarantine.length === 0 ? (
            <EmptyState icon={<ShieldCheck size={20} />} title={t("quality.none")} />
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label={t("quality.recent")}>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">{t("quality.receivedAt")}</th>
                    <th scope="col">{t("quality.reason")}</th>
                  </tr>
                </thead>
                <tbody>
                  {q.recent_quarantine.map((r, i) => (
                    <tr key={`${r.received_at}-${i}`}>
                      <td className="num">{formatDateTime(r.received_at)}</td>
                      <td>{quarantineLabel(t, r.reason)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
