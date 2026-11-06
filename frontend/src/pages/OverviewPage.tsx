import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, type SystemStatus } from "../api/client";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorState, LoadingState } from "../components/ui/StateView";
import type { useSystemStatus } from "../hooks/useSystemStatus";
import { formatTime } from "../lib/format";
import { ControlPanel } from "./overview/ControlPanel";
import { MarketViewCard } from "./overview/MarketViewCard";
import { MetricCards } from "./overview/MetricCards";
import { SafetyHistory } from "./overview/SafetyHistory";

type Sys = ReturnType<typeof useSystemStatus>;

export function OverviewPage({ sys }: { sys: Sys }) {
  const { t } = useTranslation();
  const { status, loading, connection, stale, lastSuccessAt, refresh, mutate } = sys;

  return (
    <div className="page" id="overview">
      <div className="page__head">
        <div>
          <h1 className="page__title">{t("overview.title")}</h1>
          <p className="page__subtitle">{t("overview.subtitle")}</p>
        </div>
      </div>

      {stale && (
        <div className="banner banner--warn" role="status">
          <AlertTriangle size={16} className="tone-gold" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("overview.staleBannerTitle")}</div>
            <div>
              {t("overview.staleBannerDesc", {
                time: formatTime(lastSuccessAt ? new Date(lastSuccessAt) : null),
              })}
            </div>
          </div>
          <Button variant="secondary" onClick={() => void refresh()}>
            {t("overview.retry")}
          </Button>
        </div>
      )}

      {!status && loading && (
        <Card>
          <LoadingState label={t("overview.loading")} />
        </Card>
      )}
      {!status && !loading && (
        <Card>
          <ErrorState
            title={t("overview.loadErrorTitle")}
            description={t("overview.loadErrorDesc")}
            retryLabel={t("overview.retry")}
            onRetry={() => void refresh()}
          />
        </Card>
      )}

      {(status || loading) && <MetricCards status={status} />}

      {status && <OverviewBody status={status} connection={connection} mutate={mutate} />}
    </div>
  );
}

function OverviewBody({
  status,
  connection,
  mutate,
}: {
  status: SystemStatus;
  connection: Sys["connection"];
  mutate: Sys["mutate"];
}) {
  return (
    <>
      <div className="grid-main">
        <ControlPanel
          status={status}
          disabled={connection === "disconnected"}
          onSafety={(cmd) => mutate(() => api.safety(cmd))}
          onMode={(mode) => mutate(() => api.mode({ mode, checklist: {} }))}
        />
        <MarketViewCard view={status.market_view} />
      </div>
      <SafetyHistory items={status.safety_history} />
    </>
  );
}
