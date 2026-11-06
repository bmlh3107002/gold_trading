import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { api, type AccountSummary } from "../api/client";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/StateView";
import { usePolling } from "../hooks/usePolling";

/** Trang "Tài khoản" của USER: trạng thái token Gateway (DEC-16: token do Quản trị cấp). */
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
  const d = info.data;
  return (
    <Card title={t("accountPage.gateway")} description={t("accountPage.gatewayDesc")} labelledBy="gateway-title">
      {d && (
        <ul className="plain-list">
          <li>{d.has_token ? t("accountPage.hasToken") : t("accountPage.noToken")}</li>
          {d.legacy_token_active && <li className="tone-gold">{t("accountPage.legacyActive")}</li>}
          {!d.price_feed && <li>{t("accountPage.noPriceFeed")}</li>}
        </ul>
      )}
    </Card>
  );
}
