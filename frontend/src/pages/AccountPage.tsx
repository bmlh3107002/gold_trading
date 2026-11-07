import { KeyRound, Link2, Unlink } from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError, type AccountSummary, type GatewayStatus, type Mt5LinkOut } from "../api/client";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Field } from "../components/ui/Field";
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
      <Mt5LinkCard account={account} />
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

function LinkSummary({ link }: { link: Mt5LinkOut }) {
  const { t } = useTranslation();
  return (
    <div className="kv">
      <div>
        <div className="kv__label">{t("accountPage.mt5.login")}</div>
        <div className="kv__value">{link.login}</div>
      </div>
      <div>
        <div className="kv__label">{t("accountPage.mt5.server")}</div>
        <div className="kv__value" style={{ overflowWrap: "anywhere" }}>{link.server}</div>
      </div>
      <div>
        <div className="kv__label">{t("accountPage.mt5.company")}</div>
        <div className="kv__value">{link.company ?? EMPTY}</div>
      </div>
      <div>
        <div className="kv__label">{t("accountPage.mt5.type")}</div>
        <div className="kv__value">{t(`system.gateway.account.${link.trade_mode}`)}</div>
      </div>
    </div>
  );
}

/** MT-13: Gateway báo danh tính → USER gõ lại số login để xác nhận → ACTIVE. Backend kiểm lại mọi
 * điều kiện (khớp danh tính terminal, nhịp tim còn hạn, một MT5 một tài khoản); nút chỉ là gợi ý. */
function Mt5LinkCard({ account }: { account: AccountSummary }) {
  const { t } = useTranslation();
  const id = account.account_id;
  const fetcher = useCallback(() => api.mt5Link(id), [id]);
  const state = usePolling(fetcher, 10_000, 60_000);
  const [typed, setTyped] = useState("");
  const [real, setReal] = useState(false);
  const [askRevoke, setAskRevoke] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<"conflict" | "error" | null>(null);
  const d = state.data;
  const pending = d?.pending ?? null;
  const current = d?.current ?? null;

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setTyped("");
      setReal(false);
      setAskRevoke(false);
    } catch (e) {
      setError(e instanceof ApiError && e.kind === "conflict" ? "conflict" : "error");
    } finally {
      await state.refresh();
      setBusy(false);
    }
  }

  const canConfirm =
    !!pending &&
    d?.terminal_matches_pending === true &&
    typed.trim() === String(pending.login) &&
    (pending.trade_mode !== "REAL" || real);

  return (
    <Card title={t("accountPage.link.title")} description={t("accountPage.link.desc")} labelledBy="mt5-link-title">
      {d && !current && !pending && <p>{t("accountPage.link.none")}</p>}
      {current && (
        <>
          <p className="tone-profit">
            {t("accountPage.link.active")} · {t(`accountPage.link.status.${current.status}`)}
          </p>
          <LinkSummary link={current} />
          {current.verified_at && (
            <p className="header__label" style={{ marginTop: 12 }}>
              {t("accountPage.link.activeBy", {
                by: current.verified_by ?? EMPTY,
                time: formatDateTime(current.verified_at),
              })}
            </p>
          )}
          <div style={{ marginTop: 12 }}>
            {!askRevoke ? (
              <Button icon={<Unlink size={14} aria-hidden="true" />} disabled={busy} onClick={() => setAskRevoke(true)}>
                {t("accountPage.link.revoke")}
              </Button>
            ) : (
              <>
                <p>{t("accountPage.link.revokeAsk")}</p>
                <Button
                  variant="danger"
                  disabled={busy}
                  onClick={() => void run(() => api.revokeMt5Link(id, current.link_id))}
                >
                  {t("accountPage.link.revokeYes")}
                </Button>{" "}
                <Button variant="ghost" disabled={busy} onClick={() => setAskRevoke(false)}>
                  {t("accountPage.link.cancel")}
                </Button>
              </>
            )}
          </div>
        </>
      )}
      {!current && pending && (
        <>
          <p className="tone-gold">{t("accountPage.link.pending")}</p>
          <LinkSummary link={pending} />
          {pending.trade_mode === "REAL" && (
            <div className="banner banner--error" role="alert" style={{ marginTop: 12 }}>
              <span className="banner__body">{t("accountPage.mt5.realWarning")}</span>
            </div>
          )}
          {!d?.terminal_matches_pending && (
            <div className="banner banner--error" role="alert" style={{ marginTop: 12 }}>
              <span className="banner__body">{t("accountPage.link.notMatching")}</span>
            </div>
          )}
          <div style={{ marginTop: 12, maxWidth: 360 }}>
            <Field
              label={t("accountPage.link.typeLogin")}
              hint={t("accountPage.link.typeLoginHint")}
              inputMode="numeric"
              autoComplete="off"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </div>
          {pending.trade_mode === "REAL" && (
            <label className="check">
              <input type="checkbox" checked={real} onChange={(e) => setReal(e.target.checked)} />
              <span>{t("accountPage.link.realCheck")}</span>
            </label>
          )}
          <div style={{ marginTop: 12 }}>
            <Button
              variant="primary"
              icon={<Link2 size={14} aria-hidden="true" />}
              disabled={busy || !canConfirm}
              onClick={() =>
                void run(() =>
                  api.confirmMt5Link(id, {
                    link_id: pending.link_id,
                    login: Number(typed.trim()),
                    server: pending.server,
                    acknowledge_real: pending.trade_mode === "REAL" && real,
                  }),
                )
              }
            >
              {t("accountPage.link.confirm")}
            </Button>{" "}
            <Button variant="ghost" disabled={busy} onClick={() => void run(() => api.revokeMt5Link(id, pending.link_id))}>
              {t("accountPage.link.decline")}
            </Button>
          </div>
        </>
      )}
      {error && (
        <div className="banner banner--error" role="alert" style={{ marginTop: 12 }}>
          <span className="banner__body">{t(`accountPage.link.${error}`)}</span>
        </div>
      )}
    </Card>
  );
}
