import { AlertTriangle, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { EventLatest } from "../../api/client";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { InfoTip } from "../../components/ui/InfoTip";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/StateView";
import { formatDateTime, formatNumber } from "../../lib/format";
import { readPositioning } from "../../lib/positioning";

interface Props {
  data: EventLatest | null;
  loading: boolean;
  onRetry: () => void;
}

const tone: Record<string, BadgeTone> = { CROWDED_LONG: "gold", CROWDED_SHORT: "gold", NORMAL: "neutral", INSUFFICIENT_DATA: "neutral" };

export function PositioningCard({ data, loading, onRetry }: Props) {
  const { t } = useTranslation();
  const out = data?.output ?? null;
  const blocked = !!out && out.source_status !== "HEALTHY";
  const status = !out ? null : blocked ? "blocked" : data?.valid_now ? "valid" : "expired";
  const statusTone: BadgeTone = status === "valid" ? "profit" : status === "expired" ? "gold" : "loss";
  const f = readPositioning(out?.features as Record<string, unknown> | undefined);

  return (
    <Card
      title={
        <>
          <Users size={15} aria-hidden="true" />
          {t("positioning.title")}
        </>
      }
      description={t("positioning.desc")}
      labelledBy="positioning-title"
      actions={status && <Badge tone={statusTone} dot>{t(`positioning.status.${status}`)}</Badge>}
    >
      {!data && loading && <LoadingState label={t("positioning.loading")} />}
      {!data && !loading && <ErrorState title={t("positioning.errorTitle")} retryLabel={t("market.retry")} onRetry={onRetry} />}
      {data && !out && <EmptyState icon={<Users size={22} />} title={t("positioning.emptyTitle")} description={t("positioning.emptyDesc")} />}
      {out && blocked && (
        <div className="banner banner--error" role="alert" style={{ marginBottom: 12 }}>
          <AlertTriangle size={16} className="tone-loss" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("positioning.blockedTitle")}</div>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {out.drivers.map((d) => (
                <li key={d} className="mono">
                  {d}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {out && status === "expired" && (
        <div className="banner banner--warn" role="status" style={{ marginBottom: 12 }}>
          <div className="banner__body">{t("positioning.expiredDesc")}</div>
        </div>
      )}
      {out && !blocked && (
        <>
          <div className="banner banner--warn" role="status" style={{ marginBottom: 12 }}>
            <div className="banner__body">
              {t("positioning.lag", { date: f.reportDate ?? "—", n: formatNumber(f.lagDays, 0) })}
            </div>
          </div>
          <div className="kv" style={{ marginBottom: 12 }}>
            <div>
              <div className="kv__label">{t("positioning.net")}</div>
              <div className="kv__value">
                <span className="num">{formatNumber(f.net, 0)}</span>
                <span className="metric__hint"> · {t("positioning.netChange", { v: formatNumber(f.netChange, 0) })}</span>
              </div>
            </div>
            <div>
              <div className="kv__label">{t("positioning.netPct")}</div>
              <div className="kv__value num">{f.netPctOi != null ? `${formatNumber(f.netPctOi, 1)}%` : "—"}</div>
            </div>
            <div>
              <div className="kv__label">
                {t("positioning.crowdingLabel")}
                <InfoTip label={t("positioning.crowdingLabel")} text={t("positioning.crowdingTip")} />
              </div>
              <div className="kv__value">
                {f.crowding ? <Badge tone={tone[f.crowding]}>{t(`positioning.crowding.${f.crowding}`)}</Badge> : "—"}
                <div className="metric__hint">{t("positioning.history", { n: f.historyWeeks ?? 0, min: f.minWeeks ?? 52 })}</div>
              </div>
            </div>
          </div>
          {f.hypothesis && <p className="card__desc">{t(`positioning.hypothesis.${f.hypothesis}`)}</p>}
          <p className="card__desc">{t("positioning.etfNote")}</p>
        </>
      )}
      {out && (
        <p className="card__desc">
          {t("positioning.asOf")}: {formatDateTime(out.as_of)} · {t("positioning.version")}: <span className="mono">{out.version}</span> ·{" "}
          {t("positioning.attribution")}
        </p>
      )}
    </Card>
  );
}
