import { AlertTriangle, Landmark } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AnalystLatest } from "../../api/client";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { InfoTip } from "../../components/ui/InfoTip";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/StateView";
import { formatDateTime, formatNumber } from "../../lib/format";
import { readMacro, type RateView } from "../../lib/macro";
import dict from "../../i18n/vi";

interface Props {
  data: AnalystLatest | null;
  loading: boolean;
  onRetry: () => void;
}

const biasTone: Record<string, BadgeTone> = {
  SUPPORTIVE: "profit",
  HEADWIND: "loss",
  MIXED: "gold",
  NEUTRAL: "neutral",
  INSUFFICIENT_DATA: "neutral",
};

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

export function MacroCard({ data, loading, onRetry }: Props) {
  const { t } = useTranslation();
  const out = data?.output ?? null;
  const blocked = !!out && out.source_status !== "HEALTHY";
  const status = !out ? null : blocked ? "blocked" : data?.valid_now ? "valid" : "expired";
  const statusTone: BadgeTone = status === "valid" ? "profit" : status === "expired" ? "gold" : "loss";
  const f = readMacro(out?.features as Record<string, unknown> | undefined);

  const rateText = (r: RateView | null) =>
    r?.value ? (
      <>
        <span className="num">{r.value}%</span>
        <span className="metric__hint">
          {" "}
          · {t("macro.change5", { v: r.change_5d_bp != null ? `${formatNumber(r.change_5d_bp, 1)} đcb` : "—" })}
          {" · "}
          {r.direction ? t(`macro.dir.${r.direction}`) : t("macro.zNone")}
        </span>
      </>
    ) : (
      "—"
    );

  return (
    <Card
      title={
        <>
          <Landmark size={15} aria-hidden="true" />
          {t("macro.title")}
        </>
      }
      description={t("macro.desc")}
      labelledBy="macro-title"
      actions={status && <Badge tone={statusTone} dot>{t(`macro.status.${status}`)}</Badge>}
    >
      {!data && loading && <LoadingState label={t("macro.loading")} />}
      {!data && !loading && <ErrorState title={t("macro.errorTitle")} retryLabel={t("market.retry")} onRetry={onRetry} />}
      {data && !out && <EmptyState icon={<Landmark size={22} />} title={t("macro.emptyTitle")} description={t("macro.emptyDesc")} />}
      {out && blocked && (
        <div className="banner banner--error" role="alert" style={{ marginBottom: 12 }}>
          <AlertTriangle size={16} className="tone-loss" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("macro.blockedTitle")}</div>
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
          <div className="banner__body">{t("macro.expiredDesc")}</div>
        </div>
      )}
      {out && !blocked && (
        <>
          {f.stress.length > 0 && (
            <div className="banner banner--error" role="status" style={{ marginBottom: 12 }}>
              <div className="banner__body">{t("macro.stress", { list: f.stress.join(", ") })}</div>
            </div>
          )}
          {f.flight && (
            <div className="banner banner--warn" role="status" style={{ marginBottom: 12 }}>
              <div className="banner__body">{t("macro.flight")}</div>
            </div>
          )}
          <div className="kv" style={{ marginBottom: 12 }}>
            <Item label={t("macro.biasLabel")} tip={t("macro.biasTip")}>
              {f.bias ? <Badge tone={biasTone[f.bias]}>{t(`macro.bias.${f.bias}`)}</Badge> : "—"}
              {f.bias && f.bias !== "INSUFFICIENT_DATA" && !f.biasComplete && (
                <div className="metric__hint">{t("macro.partial")}</div>
              )}
            </Item>
            <Item label={t("macro.realYield")}>{rateText(f.realYield)}</Item>
            <Item label={t("macro.nominal10y")}>{rateText(f.nominal10y)}</Item>
            <Item label={t("macro.usd")} tip={t("macro.usdTip")}>
              {f.usd?.status === "OK" && f.usd.value != null ? (
                <>
                  <span className="num">{formatNumber(f.usd.value, 2)}</span>
                  <span className="metric__hint">
                    {" "}
                    · {t("macro.change5", { v: f.usd.change_5d_pct != null ? `${formatNumber(f.usd.change_5d_pct, 2)}%` : "—" })}
                    {" · "}
                    {f.usd.direction ? t(`macro.dir.${f.usd.direction}`) : t("macro.zNone")}
                  </span>
                </>
              ) : (
                <span className="metric__hint">{t("macro.usdMissing", { reason: f.usd?.reason ?? "—" })}</span>
              )}
            </Item>
            <Item label={t("macro.fed")} tip={t("macro.fedTip")}>
              {f.fedLean && f.fedLean in dict.macro.fedLean
                ? `${t(`macro.fedLean.${f.fedLean as keyof typeof dict.macro.fedLean}`)} (${formatNumber(f.fedSpreadBp, 0)} đcb)`
                : "—"}
            </Item>
          </div>
        </>
      )}
      {out && (
        <>
          <div className="kv" style={{ margin: "10px 0" }}>
            <Item label={t("macro.asOf")}>{formatDateTime(out.as_of)}</Item>
            <Item label={t("macro.expiresAt")}>{formatDateTime(out.expires_at)}</Item>
          </div>
          <p className="card__desc">
            {t("macro.confidenceNote")} · {t("macro.version")}: <span className="mono">{out.version}</span>
          </p>
        </>
      )}
    </Card>
  );
}
