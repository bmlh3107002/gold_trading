import { Activity, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LiveQuote } from "../../api/client";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { EmptyState, LoadingState } from "../../components/ui/StateView";
import { formatDateTime, formatNumber, formatPrice } from "../../lib/format";

const STATE_TONE: Record<LiveQuote["state"], BadgeTone> = {
  LIVE: "profit",
  STALE: "loss",
  CLOSED: "neutral",
  NO_DATA: "neutral",
  NO_FEED: "neutral",
};

/** DSH-07: bid/ask/spread của nguồn giá chính tài khoản. Giá cũ khi thị trường mở → báo đỏ. */
export function LiveQuoteCard({ q, loading }: { q: LiveQuote | null; loading: boolean }) {
  const { t } = useTranslation();
  const hasPrice = !!q && q.bid != null && q.ask != null;
  const known = new Set(["WIDE_SPREAD", "SPREAD_UNRATED", "CALENDAR_CLOSED"]);
  return (
    <Card
      title={t("quote.title")}
      description={t("quote.desc")}
      labelledBy="quote-title"
      actions={q ? <Badge tone={STATE_TONE[q.state]} dot={q.state === "LIVE"}>{t(`quote.state.${q.state}`)}</Badge> : undefined}
    >
      {!q && loading && <LoadingState label={t("quote.loading")} />}
      {q?.state === "STALE" && (
        <div className="banner banner--error" role="status" style={{ marginBottom: 12 }}>
          <AlertTriangle size={16} className="tone-loss" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("quote.staleTitle")}</div>
            <div>{t("quote.staleDesc", { seconds: formatNumber(q.age_seconds, 0) })}</div>
          </div>
        </div>
      )}
      {q && (q.state === "NO_FEED" || q.state === "NO_DATA") && (
        <EmptyState
          icon={<Activity size={20} />}
          title={t(`quote.state.${q.state}`)}
          description={q.state === "NO_FEED" ? t("quote.noFeedDesc") : t("quote.noDataDesc")}
        />
      )}
      {q && hasPrice && (
        <>
          <div className={`kv ${q.state === "STALE" ? "tone-neutral" : ""}`}>
            <div>
              <div className="kv__label">{t("quote.bid")}</div>
              <div className="kv__value">{formatPrice(q.bid)}</div>
            </div>
            <div>
              <div className="kv__label">{t("quote.ask")}</div>
              <div className="kv__value">{formatPrice(q.ask)}</div>
            </div>
            <div>
              <div className="kv__label">{t("quote.spread")}</div>
              <div className="kv__value">
                {t("quote.spreadValue", {
                  points: formatNumber(q.spread_points, 0),
                  price: formatPrice((q.ask as number) - (q.bid as number)),
                })}
              </div>
              {q.spread_max_points != null && q.spread_max_points !== q.spread_points && (
                <div className="kv__label">{t("quote.spreadMax", { points: formatNumber(q.spread_max_points, 0) })}</div>
              )}
            </div>
            <div>
              <div className="kv__label">{t("quote.time")}</div>
              <div className="kv__value">{formatDateTime(q.t)}</div>
              <div className="kv__label">{t("quote.age", { seconds: formatNumber(q.age_seconds, 0) })}</div>
            </div>
          </div>
          {q.state === "CLOSED" && <p className="kv__label" style={{ marginTop: 8 }}>{t("quote.closedDesc")}</p>}
          {(q.flags ?? []).length > 0 && (
            <div className="btn-row" style={{ marginTop: 12 }} aria-label={t("market.flagsLabel")}>
              {(q.flags ?? []).map((f) => (
                <Badge key={f} tone={f === "WIDE_SPREAD" || f === "CALENDAR_CLOSED" ? "loss" : "neutral"}>
                  {known.has(f) ? t(`quote.flags.${f as "WIDE_SPREAD"}`) : f}
                </Badge>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
