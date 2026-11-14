import { Workflow } from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { api, type PipelineJob, type PipelineResponse } from "../api/client";
import { Badge, type BadgeTone } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { EmptyState, LoadingState } from "../components/ui/StateView";
import { usePolling } from "../hooks/usePolling";
import vi from "../i18n/vi";
import { formatDateTime, formatNumber } from "../lib/format";

type State = PipelineJob["state"];
const STATE_TONE: Record<State, BadgeTone> = {
  PENDING: "info",
  RUNNING: "info",
  SUCCEEDED: "profit",
  FAILED: "gold",
  DEAD: "loss",
  NO_HANDLER: "neutral",
  SUPERSEDED: "neutral",
};

/** Loại job mới chưa có bản dịch → hiện nguyên mã (không vỡ trang). */
function jobType(t: TFunction, code: string): string {
  return code in vi.pipeline.jobType ? t(`pipeline.jobType.${code as "TECHNICAL"}`) : code;
}

function laneName(t: TFunction, lane: string): string {
  return lane in vi.pipeline.lane ? t(`pipeline.lane.${lane as "spread"}`) : lane;
}

function StateBadge({ state }: { state: State }) {
  const { t } = useTranslation();
  return (
    <Badge tone={STATE_TONE[state]} dot>
      {t(`pipeline.state.${state}`)}
    </Badge>
  );
}

function JobTable({ jobs, label }: { jobs: PipelineJob[]; label: string }) {
  const { t } = useTranslation();
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={label}>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{t("pipeline.col.type")}</th>
            <th scope="col">{t("pipeline.col.event")}</th>
            <th scope="col">{t("pipeline.col.created")}</th>
            <th scope="col">{t("pipeline.col.state")}</th>
            <th scope="col">{t("pipeline.col.attempts")}</th>
            <th scope="col">{t("pipeline.col.error")}</th>
            <th scope="col">{t("pipeline.col.output")}</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={`${j.job_type}|${j.event_type}|${j.subject}|${j.created_at}`}>
              <td>
                <div>{jobType(t, j.job_type)}</div>
                <div className="muted" style={{ fontSize: 12 }}>{j.analyzer_version}</div>
              </td>
              <td>
                <div>{j.event_type}</div>
                <div className="muted" style={{ fontSize: 12, wordBreak: "break-all" }}>{j.subject}</div>
              </td>
              <td className="num">{formatDateTime(j.created_at)}</td>
              <td>
                <StateBadge state={j.state} />
              </td>
              <td className="num">{formatNumber(j.attempts, 0)}</td>
              <td>{j.error_code ?? "—"}</td>
              <td className="muted" style={{ fontSize: 12, wordBreak: "break-all" }}>{j.output_ref ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Body({ d }: { d: PipelineResponse }) {
  const { t } = useTranslation();
  return (
    <>
      <Card title={t("pipeline.lanesTitle")} description={t("pipeline.lanesDesc")}>
        {d.lanes.length === 0 ? (
          <p className="muted">{t("pipeline.noLanes")}</p>
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label={t("pipeline.lanesTitle")}>
            <table className="table">
              <tbody>
                {d.lanes.map((l) => (
                  <tr key={l.lane}>
                    <td>{laneName(t, l.lane)}</td>
                    <td>
                      <Badge tone={l.ok ? "profit" : "loss"} dot>
                        {l.ok ? t("pipeline.laneOk") : t("pipeline.laneBad")}
                      </Badge>
                    </td>
                    <td className="num">
                      {t("pipeline.lastOk")}: {formatDateTime(l.last_ok_at)}
                    </td>
                    <td className="num">{l.backlog_since ? `${t("pipeline.backlog")}: ${formatDateTime(l.backlog_since)}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          {t("pipeline.breaches", {
            n: d.budget_breaches,
            ms: d.last_latency_ms === null || d.last_latency_ms === undefined ? "—" : `${formatNumber(d.last_latency_ms, 0)} ms`,
          })}
        </p>
      </Card>

      <Card title={t("pipeline.deadTitle", { days: d.dead_window_days })} description={t("pipeline.deadDesc")}>
        {d.dead_letter.length === 0 ? <p className="muted">{t("pipeline.noDead")}</p> : <JobTable jobs={d.dead_letter} label={t("pipeline.deadTitle", { days: d.dead_window_days })} />}
      </Card>

      <Card
        title={t("pipeline.openTitle")}
        description={d.stuck_jobs > 0 ? t("pipeline.stuck", { n: d.stuck_jobs }) : undefined}
      >
        {d.open_jobs.length === 0 ? <p className="muted">{t("pipeline.noOpen")}</p> : <JobTable jobs={d.open_jobs} label={t("pipeline.openTitle")} />}
      </Card>

      <Card title={t("pipeline.countsTitle", { hours: d.window_hours })}>
        <div className="table-wrap" tabIndex={0} role="region" aria-label={t("pipeline.countsTitle", { hours: d.window_hours })}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("pipeline.col.type")}</th>
                <th scope="col">{t("pipeline.col.state")}</th>
                <th scope="col">{t("pipeline.col.count")}</th>
              </tr>
            </thead>
            <tbody>
              {d.counts.map((c) => (
                <tr key={`${c.job_type}|${c.state}`}>
                  <td>{jobType(t, c.job_type)}</td>
                  <td>
                    <StateBadge state={c.state} />
                  </td>
                  <td className="num">{formatNumber(c.count, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title={t("pipeline.recentTitle")}>
        <JobTable jobs={d.recent} label={t("pipeline.recentTitle")} />
      </Card>
    </>
  );
}

/** DSH-08 (GĐ2 bước 5): trạng thái bộ điều phối sự kiện + làn nhanh. Chỉ đọc. */
export function PipelinePage() {
  const { t } = useTranslation();
  const res = usePolling(api.pipeline, 10_000, 60_000);
  const d = res.data;
  return (
    <div className="page" id="pipeline">
      <div className="page__head">
        <div>
          <h1 className="page__title">{t("pipeline.title")}</h1>
          <p className="page__subtitle">
            {t("pipeline.subtitle")}
            {d ? ` · ${t("pipeline.asOf", { time: formatDateTime(d.as_of) })}` : ""}
          </p>
        </div>
      </div>
      {!d ? (
        <Card>
          <LoadingState label={t("market.loading")} />
        </Card>
      ) : !d.orchestrator_enabled ? (
        <Card>
          <EmptyState icon={<Workflow size={20} />} title={t("pipeline.offTitle")} description={t("pipeline.offDesc")} />
        </Card>
      ) : (
        <Body d={d} />
      )}
      <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>{t("pipeline.note")}</p>
    </div>
  );
}
