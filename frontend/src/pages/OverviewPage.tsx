import { AlertTriangle, OctagonX } from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError, type AccountStatus, type Me } from "../api/client";
import { Dialog } from "../components/ui/Dialog";
import { usePolling } from "../hooks/usePolling";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState, LoadingState } from "../components/ui/StateView";
import type { useSystemStatus } from "../hooks/useSystemStatus";
import { formatTime } from "../lib/format";
import { ControlPanel } from "./overview/ControlPanel";
import { MarketViewCard } from "./overview/MarketViewCard";
import { MetricCards } from "./overview/MetricCards";
import { SafetyHistory } from "./overview/SafetyHistory";

type Sys = ReturnType<typeof useSystemStatus>;

export function OverviewPage({ sys, accountId, me }: { sys: Sys; accountId: string | null; me: Me }) {
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
        {me.is_admin && <GlobalKillSwitch onDone={() => void refresh()} />}
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

      {status && accountId && (
        <OverviewBody status={status} accountId={accountId} me={me} connection={connection} mutate={mutate} />
      )}
    </div>
  );
}

function OverviewBody({
  status,
  accountId,
  me,
  connection,
  mutate,
}: {
  status: AccountStatus;
  accountId: string;
  me: Me;
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
          me={me.username}
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
          onApproveLive={async (rid) => {
            const err = await mutate(() => api.approveLive(accountId, rid));
            await live.refresh();
            return err;
          }}
        />
        <MarketViewCard view={status.market_view} />
      </div>
      <SafetyHistory items={status.safety_history} />
    </>
  );
}

/** Kill switch toàn hệ thống (chỉ ADMIN): HALT mọi tài khoản. Backend vẫn kiểm quyền. */
function GlobalKillSwitch({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  async function confirm() {
    setBusy(true);
    setError(false);
    try {
      await api.killSwitch("MANUAL_GLOBAL_HALT");
      setOpen(false);
      onDone();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button variant="danger" icon={<OctagonX size={14} aria-hidden="true" />} onClick={() => setOpen(true)}>
        {t("accounts.killAll")}
      </Button>
      <Dialog
        open={open}
        title={t("accounts.killAllTitle")}
        description={t("accounts.killAllDesc")}
        closeLabel={t("dialog.close")}
        onClose={() => setOpen(false)}
        actions={
          <>
            <Button variant="secondary" data-autofocus onClick={() => setOpen(false)}>
              {t("dialog.cancel")}
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => void confirm()}>
              {t("accounts.killAllConfirm")}
            </Button>
          </>
        }
      >
        {error && (
          <div className="banner banner--error" role="alert">
            <span className="banner__body">{t("errors.server")}</span>
          </div>
        )}
      </Dialog>
    </>
  );
}
