import { Activity, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AnalystLatest } from "../../api/client";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { InfoTip } from "../../components/ui/InfoTip";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/StateView";
import { formatDateTime, formatNumber, formatPercent } from "../../lib/format";
import { BLOCKING_FLAGS, NOTICE_FLAGS, readTechnical, type Level } from "../../lib/technical";

interface Props {
  data: AnalystLatest | null;
  loading: boolean;
  onRetry: () => void;
}

const trendTone: Record<string, BadgeTone> = { UP: "profit", DOWN: "loss", FLAT: "neutral" };

function Item({ label, tip, children }: { label: string; tip?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="kv__label">
        {label}
        {tip && <InfoTip label={label} text={tip} />}
      </div>
      <div className="kv__value">{children}</div>
    </div>
  );
}

export function TechnicalCard({ data, loading, onRetry }: Props) {
  const { t } = useTranslation();
  const out = data?.output ?? null;
  const blocking = out ? out.quality_flags.filter((f) => (BLOCKING_FLAGS as readonly string[]).includes(f)) : [];
  const notices = out
    ? [...out.quality_flags, ...out.risk_flags].filter((f) => (NOTICE_FLAGS as readonly string[]).includes(f))
    : [];
  const status = !out ? null : blocking.length > 0 ? "blocked" : data?.valid_now ? "valid" : "expired";
  const statusTone: BadgeTone = status === "valid" ? "profit" : status === "expired" ? "gold" : "loss";
  const f = readTechnical(out?.features as Record<string, unknown> | undefined);

  const levelText = (lv: Level | null) =>
    lv ? (
      <>
        <span className="num">{formatNumber(lv.price)}</span>
        <span className="metric__hint">
          {" "}
          · {t("technical.distance", { n: formatNumber(lv.distance_atr ?? null, 1) })} ·{" "}
          {t("technical.touches", { n: lv.touches })}
        </span>
      </>
    ) : (
      "—"
    );

  return (
    <Card
      title={
        <>
          <Activity size={15} aria-hidden="true" />
          {t("technical.title")}
        </>
      }
      description={t("technical.desc")}
      labelledBy="technical-title"
      actions={status && <Badge tone={statusTone} dot>{t(`technical.status.${status}`)}</Badge>}
    >
      {!data && loading && <LoadingState label={t("technical.loading")} />}
      {!data && !loading && (
        <ErrorState title={t("technical.errorTitle")} retryLabel={t("market.retry")} onRetry={onRetry} />
      )}
      {data && !out && (
        <EmptyState
          icon={<Activity size={22} />}
          title={t("technical.emptyTitle")}
          description={data.is_sample || data.computed_at ? t("technical.emptyDesc") : t("technical.noSource")}
        />
      )}
      {out && (
        <>
          {notices.length > 0 && (
            <div className="btn-row" style={{ marginBottom: 12 }}>
              {notices.map((fl) => (
                <Badge key={fl} tone={fl === "SAMPLE_DATA" ? "gold" : "loss"}>
                  {t(`technical.flag.${fl as (typeof NOTICE_FLAGS)[number]}`)}
                </Badge>
              ))}
            </div>
          )}

          {status === "blocked" && (
            <div className="banner banner--error" role="alert" style={{ marginBottom: 12 }}>
              <AlertTriangle size={16} className="tone-loss" aria-hidden="true" />
              <div className="banner__body">
                <div className="banner__title">{t("technical.blockedTitle")}</div>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {blocking.map((fl) => (
                    <li key={fl}>{t(`technical.flag.${fl as (typeof BLOCKING_FLAGS)[number]}`)}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {status === "expired" && (
            <div className="banner banner--warn" role="status" style={{ marginBottom: 12 }}>
              <div className="banner__body">{t("technical.expiredDesc")}</div>
            </div>
          )}

          {status !== "blocked" && (
            <div className="kv" style={{ marginBottom: 14 }}>
              <Item label={t("technical.trend")} tip={t("technical.trendTip")}>
                {f.trend ? <Badge tone={trendTone[f.trend]}>{t(`technical.trendValue.${f.trend}`)}</Badge> : "—"}
              </Item>
              <Item label={t("technical.structure")} tip={t("technical.structureTip")}>
                {f.structure ? t(`technical.structureValue.${f.structure}`) : "—"}
              </Item>
              <Item label={t("technical.atr")} tip={t("technical.atrTip")}>
                <span className="num">{formatNumber(f.atr14)}</span>
                <span className="metric__hint"> ({formatPercent(f.atr_pct)})</span>
              </Item>
              <Item label={t("technical.volRatio")} tip={t("technical.volRatioTip")}>
                <span className={`num ${f.vol_ratio != null && f.vol_ratio > 2 ? "tone-loss" : ""}`}>
                  {f.vol_ratio != null ? `${formatNumber(f.vol_ratio)}×` : "—"}
                </span>
              </Item>
              <Item label={t("technical.rsi")} tip={t("market.rsiTip")}>
                <span className="num">{formatNumber(f.rsi14)}</span>
              </Item>
              <Item label={t("technical.coverage")}>
                <span className="num">{formatPercent(f.coverage)}</span>
              </Item>
              <Item label={t("technical.volDay")} tip={t("technical.volDayTip")}>
                <span className="num">{f.volDayPct != null ? `±${formatNumber(f.volDayPct, 2)}%` : "—"}</span>
              </Item>
              <Item label={t("technical.mtf")} tip={t("technical.mtfTip")}>
                <span className="mono">
                  {f.mtf.map((m) => `${m.tf} ${m.trend === "UP" ? "↑" : m.trend === "DOWN" ? "↓" : m.trend === "FLAT" ? "→" : "—"}`).join(" · ")}
                </span>
                {f.mtfAlignment && <div className="metric__hint">{t(`technical.mtfAlignment.${f.mtfAlignment}`)}</div>}
              </Item>
              <Item label={t("technical.support")} tip={t("technical.levelTip")}>
                {levelText(f.nearest_support)}
              </Item>
              <Item label={t("technical.resistance")} tip={t("technical.levelTip")}>
                {levelText(f.nearest_resistance)}
              </Item>
            </div>
          )}

          <div className="kv" style={{ marginBottom: 10 }}>
            <Item label={t("technical.asOf")}>{formatDateTime(out.as_of)}</Item>
            <Item label={t("technical.expiresAt")}>{formatDateTime(out.expires_at)}</Item>
          </div>
          <p className="card__desc">
            {t("technical.confidenceNote")} · {t("technical.version")}: <span className="mono">{out.version}</span>
          </p>
        </>
      )}
    </Card>
  );
}
