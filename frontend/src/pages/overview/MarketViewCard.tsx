import { CandlestickChart } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MarketViewLatest } from "../../api/client";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { InfoTip } from "../../components/ui/InfoTip";
import { EmptyState } from "../../components/ui/StateView";
import { formatDateTime, formatNumber, formatPercent } from "../../lib/format";
import { biasLabel, biasTone, regimeLabel } from "../../lib/labels";
import { confidenceLevel, mvCode } from "../../lib/marketViewLabels";

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

type EmptyKind = "NONE" | "EXPIRED" | "INVALIDATED" | "NO_SOURCE" | "STALE";

/** GĐ4 bước 6 (MKV-03): nhận định thị trường của nguồn giá tài khoản.
 * An toàn: mất kết nối (``stale``) → không hiện nhận định cũ; quá ``expires_at`` theo đồng hồ trình
 * duyệt → coi như hết hạn dù máy chủ chưa báo. */
export function MarketViewCard({
  latest,
  stale = false,
  now = Date.now(),
}: {
  latest: MarketViewLatest | null | undefined;
  stale?: boolean;
  now?: number;
}) {
  const { t } = useTranslation();
  let view = latest?.market_view ?? null;
  let kind: EmptyKind | null = null;
  if (stale) {
    kind = "STALE";
    view = null;
  } else if (view && Date.parse(view.expires_at) <= now) {
    kind = "EXPIRED";
    view = null;
  } else if (!view) {
    kind = latest && latest.state !== "VALID" ? latest.state : "NONE";
  }
  const level = view ? confidenceLevel(view.confidence) : null;
  const flags = view?.quality_flags ?? [];
  const notes = flags.filter(
    (f) => f !== "UNVALIDATED_RULES" && f !== "UNCALIBRATED" && f !== "SAMPLE_DATA",
  );
  return (
    <Card
      title={t("marketView.title")}
      labelledBy="mv-title"
      actions={
        view && (
          <>
            <Badge tone={biasTone[view.bias]}>{biasLabel(t, view.bias)}</Badge>
            {flags.includes("UNVALIDATED_RULES") && (
              <Badge tone="gold">{t("marketView.unvalidated")}</Badge>
            )}
            {flags.includes("SAMPLE_DATA") && <Badge tone="info">{t("marketView.sample")}</Badge>}
          </>
        )
      }
    >
      {!view ? (
        <div data-testid="mv-empty">
          <EmptyState
            icon={<CandlestickChart size={22} />}
            title={
              kind === "STALE"
                ? t("overview.staleBannerTitle")
                : t(`marketView.stateTitle.${(kind ?? "NONE") as "NONE"}`)
            }
            description={t("marketView.noSignal")}
          />
          {kind === "INVALIDATED" && latest?.invalidation_reason && (
            <p className="tone-neutral" data-testid="mv-invalidated">
              {t("marketView.invalidatedBecause", {
                reason: mvCode(t, latest.invalidation_reason),
              })}
            </p>
          )}
          {kind !== "STALE" && latest?.gate?.verdict === "REJECTED" && (
            <div data-testid="mv-gate">
              <div className="kv__label">{t("marketView.gateRejected")}</div>
              <ul>
                {latest.gate.reasons.map((r) => (
                  <li key={r}>{mvCode(t, r)}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <>
          <p className="tone-neutral" data-testid="mv-unvalidated-note">
            {t("marketView.unvalidatedNote")}
          </p>
          <div className="kv">
            <Item label={t("marketView.probability")} tip={t("marketView.pTip")}>
              {view.p_up == null || view.p_down == null ? (
                <span className="tone-neutral" data-testid="mv-prob-none">
                  {t("marketView.uncalibrated")}
                </span>
              ) : (
                <>
                  <span className="tone-profit">{formatPercent(view.p_up)}</span>
                  {" / "}
                  <span className="tone-loss">{formatPercent(view.p_down)}</span>
                </>
              )}
            </Item>
            <Item
              label={t("marketView.confidence")}
              tip={
                level
                  ? t("marketView.confidenceTip", { raw: formatNumber(view.confidence) })
                  : t("marketView.confidenceTipNone")
              }
            >
              {level ? (
                <span data-testid="mv-confidence">{t(`marketView.confidenceLevel.${level}`)}</span>
              ) : (
                <span className="tone-neutral" data-testid="mv-confidence">
                  {t("marketView.noData")}
                </span>
              )}
            </Item>
            <Item label={t("marketView.regime")} tip={t("marketView.regimeTip")}>
              {regimeLabel(t, view.regime)}
            </Item>
            <Item label={t("marketView.volForecast")} tip={t("marketView.volTip")}>
              {view.vol_forecast == null ? (
                <span className="tone-neutral">{t("marketView.noData")}</span>
              ) : (
                `${formatNumber(view.vol_forecast)} %`
              )}
            </Item>
            <Item label={t("marketView.riskFlags")}>
              {view.risk_flags && view.risk_flags.length > 0 ? (
                <span data-testid="mv-risk">{view.risk_flags.map((f) => mvCode(t, f)).join(", ")}</span>
              ) : (
                <span className="tone-neutral">{t("marketView.noFlags")}</span>
              )}
            </Item>
            <Item label={t("marketView.asOf")}>{formatDateTime(view.as_of)}</Item>
            <Item label={t("marketView.expiresAt")}>{formatDateTime(view.expires_at)}</Item>
          </div>
          {view.drivers && view.drivers.length > 0 && (
            <div data-testid="mv-drivers">
              <div className="kv__label">{t("marketView.drivers")}</div>
              <ul>
                {view.drivers.map((d) => (
                  <li key={d}>{mvCode(t, d)}</li>
                ))}
              </ul>
            </div>
          )}
          {notes.length > 0 && (
            <div data-testid="mv-notes">
              <div className="kv__label">{t("marketView.qualityFlags")}</div>
              <ul>
                {notes.map((f) => (
                  <li key={f}>{mvCode(t, f)}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
