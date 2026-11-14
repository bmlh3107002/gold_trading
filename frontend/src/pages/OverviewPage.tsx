import { AlertTriangle } from "lucide-react";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError, type AccountStatus } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState, LoadingState } from "../components/ui/StateView";
import type { useSystemStatus } from "../hooks/useSystemStatus";
import { formatTime } from "../lib/format";
import { ControlPanel } from "./overview/ControlPanel";
import { EntryBlockBanner } from "./overview/EntryBlockBanner";
import { MarketViewCard } from "./overview/MarketViewCard";
import { MetricCards } from "./overview/MetricCards";
import { SafetyHistory } from "./overview/SafetyHistory";

type Sys = ReturnType<typeof useSystemStatus>;

export function OverviewPage({ sys, accountId }: { sys: Sys; accountId: string | null }) {
  const { t } = useTranslation();
  const { status, loading, connection, stale, lastSuccessAt, refresh, mutate } = sys;

  if (!accountId && !loading) {
    return (
      <div className="page" id="overview">
        <Card>
          <EmptyState title={t("accounts.noneTitle")} description={t("accounts.noneDesc")} />
        </Card>
      </div>
    );
  }

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

      {status && <EntryBlockBanner status={status} />}

      {(status || loading) && <MetricCards status={status} />}

      {status && accountId && (
        <OverviewBody status={status} accountId={accountId} connection={connection} mutate={mutate} />
      )}
    </div>
  );
}

function OverviewBody({
  status,
  accountId,
  connection,
  mutate,
}: {
  status: AccountStatus;
  accountId: string;
  connection: Sys["connection"];
  mutate: Sys["mutate"];
}) {
  const fetchLive = useCallback(() => api.liveRequests(accountId), [accountId]);
  const live = usePolling(fetchLive, 5000, 20_000);
  const asError = (e: unknown) => (e instanceof ApiError ? e : new ApiError("server", null));
  return (
    <>
      <div className="grid-main">
        <ControlPanel
          status={status}
          disabled={connection === "disconnected"}
          liveRequests={live.data ?? []}
          onSafety={(cmd) => mutate(() => api.safety(accountId, cmd))}
          onMode={(mode) => mutate(() => api.mode(accountId, { mode, checklist: {} }))}
          onRequestLive={async () => {
            try {
              await api.requestLive(accountId, {});
              await live.refresh();
              return null;
            } catch (e) {
              return asError(e);
            }
          }}
        />
        <MarketViewCard view={status.market_view} />
      </div>
      <SafetyHistory items={status.safety_history} />
    </>
  );
}
