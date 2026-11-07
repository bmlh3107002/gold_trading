import { KeyRound } from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type AccountSummary } from "../api/client";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/StateView";
import { usePolling } from "../hooks/usePolling";
import { formatDateTime } from "../lib/format";

/** Trang "Tài khoản" của USER: trạng thái token Gateway + xin cấp token (DEC-17: Quản trị cấp). */
export function AccountPage({ account }: { account: AccountSummary | null }) {
  const { t } = useTranslation();
  if (!account) {
    return (
      <div className="page">
        <Card>
          <EmptyState title={t("accounts.noneTitle")} description={t("accounts.noneDesc")} />
        </Card>
      </div>
    );
  }
  return (
    <div className="page" id="account">
      <div className="page__head">
        <div>
          <h1 className="page__title">{t("accountPage.title", { name: account.name })}</h1>
          <p className="page__subtitle">{t("accountPage.subtitle")}</p>
        </div>
      </div>
      <GatewayInfo account={account} />
    </div>
  );
}

function GatewayInfo({ account }: { account: AccountSummary }) {
  const { t } = useTranslation();
  const fetcher = useCallback(() => api.gatewayTokenInfo(account.account_id), [account.account_id]);
  const info = usePolling(fetcher, 30_000, 120_000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const d = info.data;

  async function ask() {
    setBusy(true);
    setError(false);
    try {
      await api.requestGatewayToken(account.account_id);
      await info.refresh();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={t("accountPage.gateway")} description={t("accountPage.gatewayDesc")} labelledBy="gateway-title">
      {d && (
        <>
          <ul className="plain-list">
            <li>{d.has_token ? t("accountPage.hasToken") : t("accountPage.noToken")}</li>
            {d.legacy_token_active && <li className="tone-gold">{t("accountPage.legacyActive")}</li>}
            {!d.price_feed && <li>{t("accountPage.noPriceFeed")}</li>}
            {d.request_status === "PENDING" && d.requested_at && (
              <li className="tone-gold">
                {t("accountPage.requestPending", { time: formatDateTime(d.requested_at) })}
              </li>
            )}
            {d.request_status === "REJECTED" && d.requested_at && (
              <li className="tone-loss">
                {t("accountPage.requestRejected", { time: formatDateTime(d.requested_at) })}
              </li>
            )}
          </ul>
          {error && (
            <div className="banner banner--error" role="alert" style={{ marginTop: 12 }}>
              <span className="banner__body">{t("accountPage.requestError")}</span>
            </div>
          )}
          {d.request_status !== "PENDING" && (
            <div style={{ marginTop: 12 }}>
              <Button
                variant={d.has_token ? "secondary" : "primary"}
                icon={<KeyRound size={14} aria-hidden="true" />}
                disabled={busy}
                onClick={() => void ask()}
              >
                {d.has_token ? t("accountPage.requestTokenAgain") : t("accountPage.requestToken")}
              </Button>
              {d.has_token && <p className="header__label">{t("accountPage.requestTokenHint")}</p>}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
