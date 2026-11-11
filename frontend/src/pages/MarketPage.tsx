import { AlertTriangle, CandlestickChart, FlaskConical } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PriceChart } from "../components/chart/PriceChart";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { InfoTip } from "../components/ui/InfoTip";
import { EmptyState, ErrorState, LoadingState } from "../components/ui/StateView";
import { useCandles, useDataQuality, useMarketSummary, useTechnical } from "../hooks/useMarket";
import type { Theme } from "../hooks/useTheme";
import { formatDateTime, formatNumber, formatTime } from "../lib/format";
import { flagLabel } from "../lib/labels";
import { readTechnical } from "../lib/technical";
import { DataQualityCard } from "./market/DataQualityCard";
import { TechnicalCard } from "./market/TechnicalCard";

type SummaryState = ReturnType<typeof useMarketSummary>;

export function MarketPage({
  theme,
  summary,
  accountId,
}: {
  theme: Theme;
  summary: SummaryState;
  accountId: string | null;
}) {
  const { t } = useTranslation();
  const candles = useCandles(accountId, 300);
  const quality = useDataQuality(accountId);
  const tech = useTechnical(accountId);
  // Chỉ vẽ hỗ trợ/kháng cự từ kết quả còn hiệu lực và không bị chặn bởi cổng chất lượng
  const techOut = tech.data?.output;
  const techUsable =
    !!techOut && !!tech.data?.valid_now && techOut.source_status === "HEALTHY";
  const levels = techUsable ? readTechnical(techOut?.features as Record<string, unknown>) : null;
  const srLevels = levels
    ? [levels.nearest_support, levels.nearest_resistance].flatMap((lv, i) =>
        lv ? [{ price: lv.price, kind: i === 0 ? ("S" as const) : ("R" as const) }] : [],
      )
    : [];
  const s = summary.data;
  const c = candles.data;
  const last = c?.candles.at(-1);

  return (
    <div className="page" id="market">
      <div className="page__head">
        <div>
          <h1 className="page__title">{t("market.title")}</h1>
          <p className="page__subtitle">{t("market.subtitle")}</p>
        </div>
      </div>

      {(c?.is_sample || s?.is_sample) && (
        <div className="banner banner--warn" role="note">
          <FlaskConical size={16} className="tone-gold" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("market.sampleTitle")}</div>
            <div>{t("market.sampleDesc")}</div>
          </div>
        </div>
      )}

      {s?.freshness === "STALE" && (
        <div className="banner banner--error" role="status">
          <AlertTriangle size={16} className="tone-loss" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("market.staleTitle")}</div>
            <div>{t("market.staleDesc", { time: formatDateTime(s.last_close_time) })}</div>
          </div>
        </div>
      )}

      {candles.stale && c && (
        <div className="banner banner--warn" role="status">
          <AlertTriangle size={16} className="tone-gold" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("overview.staleBannerTitle")}</div>
            <div>
              {t("overview.staleBannerDesc", {
                time: formatTime(candles.lastSuccessAt ? new Date(candles.lastSuccessAt) : null),
              })}
            </div>
          </div>
          <Button variant="secondary" onClick={() => void candles.refresh()}>
            {t("market.retry")}
          </Button>
        </div>
      )}

      <Card
        title={
          <>
            {t("market.chartTitle")}
            <InfoTip label={t("market.ema20")} text={t("market.emaTip")} />
            <InfoTip label={t("market.rsi14")} text={t("market.rsiTip")} />
          </>
        }
        description={c && c.candles.length > 0 ? t("market.chartDesc", { count: c.candles.length }) : undefined}
        labelledBy="chart-title"
        actions={
          last && last.flags.length > 0 ? (
            <span className="btn-row" aria-label={t("market.flagsLabel")}>
              {last.flags.map((f) => (
                <Badge key={f} tone={f === "PRICE_JUMP" || f === "GAP_BEFORE" ? "loss" : "neutral"}>
                  {flagLabel(t, f)}
                </Badge>
              ))}
            </span>
          ) : undefined
        }
      >
        {!c && candles.loading && <LoadingState label={t("market.loading")} />}
        {!c && !candles.loading && (
          <ErrorState
            title={t("market.loadErrorTitle")}
            description={t("market.loadErrorDesc")}
            retryLabel={t("market.retry")}
            onRetry={() => void candles.refresh()}
          />
        )}
        {c && c.source === null && (
          <EmptyState icon={<CandlestickChart size={22} />} title={t("market.noSourceTitle")} description={t("market.noSourceDesc")} />
        )}
        {c && c.source !== null && c.candles.length === 0 && (
          <EmptyState icon={<CandlestickChart size={22} />} title={t("market.noDataTitle")} description={t("market.noDataDesc")} />
        )}
        {c && c.candles.length > 0 && (
          <>
            <PriceChart
              candles={c.candles}
              ema20={c.ema20}
              ema50={c.ema50}
              rsi14={c.rsi14}
              theme={theme}
              levels={srLevels}
            />
            <p className="chart-attribution">
              {t("market.attribution")} ·{" "}
              <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer noopener">
                tradingview.com
              </a>
              {last && (
                <>
                  {" "}
                  · {t("market.close")} {formatNumber(last.close)}
                </>
              )}
            </p>
          </>
        )}
      </Card>

      <div className="grid-main">
        <TechnicalCard data={tech.data} loading={tech.loading} onRetry={() => void tech.refresh()} />
        <DataQualityCard q={quality.data} />
      </div>
    </div>
  );
}
