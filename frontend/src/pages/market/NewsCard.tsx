import { AlertTriangle, Newspaper } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { EventLatest } from "../../api/client";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/StateView";
import { formatDateTime } from "../../lib/format";
import { readNews, type NewsItem } from "../../lib/news";

interface Props {
  data: EventLatest | null;
  loading: boolean;
  onRetry: () => void;
}

const impactTone: Record<string, BadgeTone> = { BULLISH: "profit", BEARISH: "loss", NEUTRAL: "neutral", UNCLEAR: "neutral" };

export function NewsCard({ data, loading, onRetry }: Props) {
  const { t } = useTranslation();
  const out = data?.output ?? null;
  const blocked = !!out && out.source_status !== "HEALTHY";
  const status = !out ? null : blocked ? "blocked" : data?.valid_now ? "valid" : "expired";
  const statusTone: BadgeTone = status === "valid" ? "profit" : status === "expired" ? "gold" : "loss";
  const f = readNews(out?.features as Record<string, unknown> | undefined);
  const all = [...f.items, ...f.unassessed].sort((a, b) => (b.firstSeenAt ?? "").localeCompare(a.firstSeenAt ?? ""));

  const row = (it: NewsItem) => (
    <li key={`${it.title}-${it.firstSeenAt}`} style={{ marginBottom: 10 }}>
      {it.assessed && it.goldImpact && (
        <>
          <Badge tone={impactTone[it.goldImpact]}>
            {t(`news.impact.${it.goldImpact}`)}
            {it.impact ? ` · ${t(`news.level.${it.impact}`)}` : ""}
          </Badge>{" "}
        </>
      )}
      {it.url ? (
        <a href={it.url} target="_blank" rel="noreferrer noopener">
          {it.title}
        </a>
      ) : (
        it.title
      )}
      <div className="metric__hint">
        {formatDateTime(it.firstSeenAt)}
        {it.source ? ` · ${it.source}` : ""}
        {it.topics ? ` · ${it.topics}` : ""}
      </div>
      {it.summaryVi && <div className="card__desc">{it.summaryVi}</div>}
      {it.quote && (
        <div className="metric__hint">
          {t("news.quote")}: “{it.quote}”
        </div>
      )}
      {it.suspect && (
        <div className="metric__hint tone-loss">
          <AlertTriangle size={12} aria-hidden="true" /> {t("news.suspect")}
        </div>
      )}
    </li>
  );

  return (
    <Card
      title={
        <>
          <Newspaper size={15} aria-hidden="true" />
          {t("news.title")}
        </>
      }
      description={t("news.desc")}
      labelledBy="news-title"
      actions={status && <Badge tone={statusTone} dot>{t(`news.status.${status}`)}</Badge>}
    >
      {!data && loading && <LoadingState label={t("news.loading")} />}
      {!data && !loading && <ErrorState title={t("news.errorTitle")} retryLabel={t("market.retry")} onRetry={onRetry} />}
      {data && !out && <EmptyState icon={<Newspaper size={22} />} title={t("news.emptyTitle")} description={t("news.emptyDesc")} />}
      {out && !blocked && (
        <>
          {f.mode === "RULES_ONLY" && (
            <div className="banner banner--warn" role="status" style={{ marginBottom: 12 }}>
              <div className="banner__body">{t("news.rulesOnly")}</div>
            </div>
          )}
          {f.shock && (
            <div className="banner banner--error" role="status" style={{ marginBottom: 12 }}>
              <div className="banner__body">{t("news.shock")}</div>
            </div>
          )}
          {f.unprocessed > 0 && <p className="card__desc">{t("news.unprocessed", { n: f.unprocessed })}</p>}
          {all.length === 0 ? (
            <p className="card__desc">{t("news.none")}</p>
          ) : (
            <ul style={{ margin: "4px 0 12px", paddingLeft: 0, listStyle: "none" }}>{all.slice(0, 10).map(row)}</ul>
          )}
          {f.mode === "LLM" && (
            <p className="card__desc">
              {t("news.aiNote")}
              {f.budget?.cap && ` · ${t("news.budget", { spent: f.budget.spent ?? "0", cap: f.budget.cap })}`}
            </p>
          )}
        </>
      )}
      {out && (
        <p className="card__desc">
          {t("news.asOf")}: {formatDateTime(out.as_of)} · {t("news.version")}: <span className="mono">{out.version}</span>
        </p>
      )}
    </Card>
  );
}
