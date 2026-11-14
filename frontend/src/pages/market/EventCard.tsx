import { AlertTriangle, CalendarClock } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { EventLatest } from "../../api/client";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { InfoTip } from "../../components/ui/InfoTip";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/StateView";
import { formatDateTime, formatDayMonth, formatNumber } from "../../lib/format";
import { blockingKind, readEvent, type EventItem } from "../../lib/event";
import dict from "../../i18n/vi";

interface Props {
  data: EventLatest | null;
  loading: boolean;
  onRetry: () => void;
}

const riskTone: Record<string, BadgeTone> = { HIGH: "loss", MEDIUM: "gold", LOW: "neutral", NONE: "profit" };
const impTone: Record<string, BadgeTone> = { HIGH: "loss", MEDIUM: "gold", LOW: "neutral" };

export function EventCard({ data, loading, onRetry }: Props) {
  const { t } = useTranslation();
  const out = data?.output ?? null;
  const blocked = !!out && out.source_status !== "HEALTHY";
  const status = !out ? null : blocked ? "blocked" : data?.valid_now ? "valid" : "expired";
  const statusTone: BadgeTone = status === "valid" ? "profit" : status === "expired" ? "gold" : "loss";
  const f = readEvent(out?.features as Record<string, unknown> | undefined);

  const name = (e: string) =>
    e in dict.eventAnalyst.eventName ? t(`eventAnalyst.eventName.${e as keyof typeof dict.eventAnalyst.eventName}`) : e;
  const blockText = (d: string) => {
    const k = blockingKind(d);
    const src = d.includes(":") ? d.slice(d.indexOf(":") + 1) : "";
    return k in dict.eventAnalyst.blocked
      ? t(`eventAnalyst.blocked.${k as keyof typeof dict.eventAnalyst.blocked}`, { src })
      : d;
  };
  const row = (it: EventItem, showActual: boolean) => (
    <li key={`${it.event}-${it.release_at}`} style={{ marginBottom: 6 }}>
      {it.importance && (
        <Badge tone={impTone[it.importance]}>{t(`eventAnalyst.importance.${it.importance}`)}</Badge>
      )}{" "}
      <strong>{name(it.event)}</strong>
      <span className="metric__hint">
        {" "}
        · {it.all_day ? `${formatDayMonth(it.release_at)} ${t("eventAnalyst.allDay")}` : formatDateTime(it.release_at)}
        {showActual && it.actual_status && (
          <>
            {" "}
            ·{" "}
            {it.actual_status in dict.eventAnalyst.actual
              ? t(`eventAnalyst.actual.${it.actual_status as keyof typeof dict.eventAnalyst.actual}`)
              : it.actual_status}
            {it.actuals.length > 0 && (
              <span className="mono"> ({it.actuals.map(([s, v]) => `${s}=${v ?? "—"}`).join(", ")})</span>
            )}
          </>
        )}
      </span>
    </li>
  );

  return (
    <Card
      title={
        <>
          <CalendarClock size={15} aria-hidden="true" />
          {t("eventAnalyst.title")}
        </>
      }
      description={t("eventAnalyst.desc")}
      labelledBy="event-analyst-title"
      actions={status && <Badge tone={statusTone} dot>{t(`eventAnalyst.status.${status}`)}</Badge>}
    >
      {!data && loading && <LoadingState label={t("eventAnalyst.loading")} />}
      {!data && !loading && (
        <ErrorState title={t("eventAnalyst.errorTitle")} retryLabel={t("market.retry")} onRetry={onRetry} />
      )}
      {data && !out && (
        <EmptyState icon={<CalendarClock size={22} />} title={t("eventAnalyst.emptyTitle")} description={t("eventAnalyst.emptyDesc")} />
      )}
      {out && blocked && (
        <div className="banner banner--error" role="alert" style={{ marginBottom: 12 }}>
          <AlertTriangle size={16} className="tone-loss" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("eventAnalyst.blockedTitle")}</div>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {out.drivers.map((d) => (
                <li key={d}>{blockText(d)}</li>
              ))}
            </ul>
            <div className="metric__hint">{t("eventAnalyst.blockedNote")}</div>
          </div>
        </div>
      )}
      {out && status === "expired" && (
        <div className="banner banner--warn" role="status" style={{ marginBottom: 12 }}>
          <div className="banner__body">{t("eventAnalyst.expiredDesc")}</div>
        </div>
      )}
      {out && !blocked && (
        <>
          <div className="kv" style={{ marginBottom: 12 }}>
            <div>
              <div className="kv__label">
                {t("eventAnalyst.risk")}
                <InfoTip label={t("eventAnalyst.risk")} text={t("eventAnalyst.riskTip")} />
              </div>
              <div className="kv__value">
                {f.event_risk ? (
                  <Badge tone={riskTone[f.event_risk]}>{t(`eventAnalyst.riskValue.${f.event_risk}`)}</Badge>
                ) : (
                  "—"
                )}
              </div>
            </div>
            <div>
              <div className="kv__label">{t("eventAnalyst.next")}</div>
              <div className="kv__value">
                {f.next_event ? (
                  <>
                    {name(f.next_event.event)}
                    <span className="metric__hint">
                      {" "}
                      ·{" "}
                      {f.next_event.minutes_until != null
                        ? t("eventAnalyst.inMinutes", { n: formatNumber(f.next_event.minutes_until, 0) })
                        : formatDateTime(f.next_event.release_at)}
                    </span>
                  </>
                ) : (
                  "—"
                )}
              </div>
            </div>
          </div>
          {f.window && (
            <div className="banner banner--error" role="status" style={{ marginBottom: 12 }}>
              <div className="banner__body">
                {t("eventAnalyst.inWindow", { time: f.window.end ? formatDateTime(f.window.end) : "—" })}
              </div>
            </div>
          )}
          {!f.window && f.soon && (
            <div className="banner banner--warn" role="status" style={{ marginBottom: 12 }}>
              <div className="banner__body">{t("eventAnalyst.soon")}</div>
            </div>
          )}
          <div className="kv__label">{t("eventAnalyst.upcoming")}</div>
          {f.upcoming.length > 0 ? (
            <ul style={{ margin: "4px 0 12px", paddingLeft: 0, listStyle: "none" }}>{f.upcoming.map((it) => row(it, false))}</ul>
          ) : (
            <p className="card__desc">{t("eventAnalyst.noUpcoming")}</p>
          )}
          {f.recent_releases.length > 0 && (
            <>
              <div className="kv__label">{t("eventAnalyst.recent")}</div>
              <ul style={{ margin: "4px 0 6px", paddingLeft: 0, listStyle: "none" }}>
                {f.recent_releases.map((it) => row(it, true))}
              </ul>
              <p className="card__desc">{t("eventAnalyst.surpriseNote")}</p>
            </>
          )}
          {f.removed.length > 0 && (
            <>
              <div className="kv__label">{t("eventAnalyst.removed")}</div>
              <ul style={{ margin: "4px 0 12px", paddingLeft: 18 }}>
                {f.removed.map((r) => (
                  <li key={`${r.event}-${r.release_at}`}>
                    {name(r.event)} <span className="metric__hint">· {formatDateTime(r.release_at)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
      {out && (
        <>
          <div className="kv" style={{ margin: "10px 0" }}>
            <div>
              <div className="kv__label">{t("eventAnalyst.asOf")}</div>
              <div className="kv__value">{formatDateTime(out.as_of)}</div>
            </div>
            <div>
              <div className="kv__label">{t("eventAnalyst.expiresAt")}</div>
              <div className="kv__value">{formatDateTime(out.expires_at)}</div>
            </div>
          </div>
          <p className="card__desc">
            {t("eventAnalyst.confidenceNote")} · {t("eventAnalyst.version")}: <span className="mono">{out.version}</span>
          </p>
        </>
      )}
    </Card>
  );
}
