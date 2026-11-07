import { KeyRound } from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type AccountSummary, type GatewayStatus } from "../api/client";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/StateView";
import { usePolling } from "../hooks/usePolling";
import { EMPTY, formatDateTime, formatMoney, formatNumber } from "../lib/format";

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
      <Mt5Info account={account} />
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

/** MT-12 + GW-09: MT5 mà Gateway đang đọc (danh tính, số liệu tài khoản, thông số symbol). Chỉ hiển
 * thị đúng số Gateway gửi; thiếu → "—", không tự tính hay đoán. */
function Mt5Info({ account }: { account: AccountSummary }) {
  const { t } = useTranslation();
  const fetcher = useCallback(() => api.gatewayStatus(account.account_id), [account.account_id]);
  const st = usePolling<GatewayStatus>(fetcher, 10_000, 60_000).data;
  const hb = st?.heartbeat ?? null;
  const id = hb?.identity ?? null;
  const acc = hb?.account ?? null;
  const sym = hb?.symbol ?? null;
  const cur = acc?.currency ?? "";
  const money = (v: number | null | undefined) => (cur ? formatMoney(v, cur) : formatNumber(v));
  const rows: [string, string][] = id
    ? [
        [t("accountPage.mt5.login"), String(id.login)],
        [t("accountPage.mt5.server"), id.server],
        [t("accountPage.mt5.company"), id.company ?? EMPTY],
        [t("accountPage.mt5.type"), t(`system.gateway.account.${id.account_type}`)],
        [t("accountPage.mt5.terminal"), id.terminal_path ?? EMPTY],
        [t("accountPage.mt5.balance"), money(acc?.balance)],
        [t("accountPage.mt5.equity"), money(acc?.equity)],
        [t("accountPage.mt5.margin"), money(acc?.margin)],
        [t("accountPage.mt5.marginFree"), money(acc?.margin_free)],
        [t("accountPage.mt5.marginLevel"), acc?.margin_level == null ? EMPTY : `${formatNumber(acc.margin_level)}%`],
        [t("accountPage.mt5.leverage"), acc?.leverage == null ? EMPTY : `1:${acc.leverage}`],
        [t("accountPage.mt5.stopsFreeze"), `${sym?.stops_level ?? EMPTY} / ${sym?.freeze_level ?? EMPTY}`],
        [t("accountPage.mt5.swap"), `${formatNumber(sym?.swap_long)} / ${formatNumber(sym?.swap_short)}`],
      ]
    : [];
  return (
    <Card title={t("accountPage.mt5.title")} description={t("accountPage.mt5.desc")} labelledBy="mt5-title">
      {st && !id && <p>{t(st.state === "NEVER" ? "accountPage.mt5.never" : "accountPage.mt5.noIdentity")}</p>}
      {id && (
        <>
          {id.account_type === "REAL" && (
            <div className="banner banner--error" role="alert" style={{ marginBottom: 12 }}>
              <span className="banner__body">{t("accountPage.mt5.realWarning")}</span>
            </div>
          )}
          <div className="kv">
            {rows.map(([k, v]) => (
              <div key={k}>
                <div className="kv__label">{k}</div>
                <div className="kv__value" style={{ overflowWrap: "anywhere" }}>{v}</div>
              </div>
            ))}
          </div>
          {st?.last_seen_at && (
            <p className="header__label" style={{ marginTop: 12 }}>
              {t("accountPage.mt5.readAt", { time: formatDateTime(st.last_seen_at) })}
            </p>
          )}
        </>
      )}
    </Card>
  );
}
