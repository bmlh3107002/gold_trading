import { Copy, KeyRound, UserMinus, UserPlus } from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  ApiError,
  type AccountSummary,
  type GatewayTokenIssued,
  type Me,
  type MemberOut,
} from "../api/client";
import { Badge } from "../components/ui/Badge";
import { Button, IconButton } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Dialog } from "../components/ui/Dialog";
import { Field } from "../components/ui/Field";
import { EmptyState, LoadingState } from "../components/ui/StateView";
import { usePolling } from "../hooks/usePolling";
import { formatDateTime } from "../lib/format";

type Role = MemberOut["role"];
const ROLES: Role[] = ["OWNER", "OPERATOR", "VIEWER"];

/** Trang "Tài khoản": thành viên + token Gateway. Nút ẩn/khóa theo quyền; backend vẫn kiểm lại. */
export function AccountPage({ account, me }: { account: AccountSummary | null; me: Me }) {
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
      <Members account={account} me={me} />
      {/* DEC-15: token Gateway chỉ Chủ tài khoản thấy; Quản trị không là thành viên thì ẩn. */}
      {account.permissions.includes("ROTATE_TOKEN") && <GatewayToken account={account} />}
    </div>
  );
}

function errorKey(e: unknown) {
  if (!(e instanceof ApiError)) return "errors.server" as const;
  if (e.status === 404) return "accountPage.userNotFound" as const;
  if (e.kind === "conflict") return "accountPage.conflict" as const;
  return `errors.${e.kind}` as const;
}

function Members({ account, me }: { account: AccountSummary; me: Me }) {
  const { t } = useTranslation();
  const canManage = account.permissions.includes("MANAGE_MEMBERS");
  const fetcher = useCallback(() => api.members(account.account_id), [account.account_id]);
  const members = usePolling(fetcher, 15_000, 60_000);
  const [user, setUser] = useState("");
  const [role, setRole] = useState<Role>("VIEWER");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await members.refresh();
    } catch (e) {
      setError(t(errorKey(e)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={t("accountPage.members")} description={t("accountPage.membersDesc")} labelledBy="members-title">
      {error && (
        <div className="banner banner--error" role="alert" style={{ marginBottom: 14 }}>
          <span className="banner__body">{error}</span>
        </div>
      )}
      {!members.data && members.loading && <LoadingState label={t("accountPage.loading")} />}
      {members.data && (
        <div className="table-wrap" tabIndex={0} role="region" aria-labelledby="members-title">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("accountPage.user")}</th>
                <th scope="col">{t("accountPage.role")}</th>
                <th scope="col">{t("accountPage.grantedAt")}</th>
                {canManage && <th scope="col">{t("accountPage.actions")}</th>}
              </tr>
            </thead>
            <tbody>
              {members.data.map((m) => (
                <tr key={m.sub}>
                  <td>
                    {m.display_name || m.username}
                    {m.username === me.username && <Badge tone="gold">{t("accountPage.you")}</Badge>}
                    {m.email && <div className="header__label">{m.email}</div>}
                  </td>
                  <td>
                    {canManage ? (
                      <select
                        className="header__select"
                        aria-label={t("accountPage.roleFor", { name: m.username })}
                        value={m.role}
                        disabled={busy}
                        onChange={(e) =>
                          void run(() => api.setMemberRole(account.account_id, m.sub, e.target.value as Role))
                        }
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {t(`accounts.role.${r}`)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      t(`accounts.role.${m.role}`)
                    )}
                  </td>
                  <td className="num">{formatDateTime(m.granted_at)}</td>
                  {canManage && (
                    <td>
                      <IconButton
                        label={t("accountPage.remove", { name: m.username })}
                        disabled={busy}
                        onClick={() => void run(() => api.removeMember(account.account_id, m.sub))}
                      >
                        <UserMinus size={16} aria-hidden="true" />
                      </IconButton>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canManage && (
        <form
          className="form-grid"
          style={{ marginTop: 14 }}
          onSubmit={(e) => {
            e.preventDefault();
            if (!user.trim()) return;
            void run(() => api.addMember(account.account_id, user.trim(), role)).then(() => setUser(""));
          }}
        >
          <Field
            label={t("accountPage.addUser")}
            hint={t("accountPage.addUserHint")}
            value={user}
            maxLength={256}
            onChange={(e) => setUser(e.target.value)}
          />
          <div className="field">
            <label className="field__label" htmlFor="new-role">
              {t("accountPage.role")}
            </label>
            <select id="new-role" className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`accounts.role.${r}`)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Button type="submit" variant="primary" disabled={busy || !user.trim()} icon={<UserPlus size={14} aria-hidden="true" />}>
              {t("accountPage.add")}
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}

function GatewayToken({ account }: { account: AccountSummary }) {
  const { t } = useTranslation();
  const canRotate = account.permissions.includes("ROTATE_TOKEN");
  const fetcher = useCallback(() => api.gatewayTokenInfo(account.account_id), [account.account_id]);
  const info = usePolling(fetcher, 30_000, 120_000);
  const [confirming, setConfirming] = useState(false);
  const [issued, setIssued] = useState<GatewayTokenIssued | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function rotate() {
    setConfirming(false);
    setError(null);
    try {
      setIssued(await api.rotateGatewayToken(account.account_id));
      setCopied(false);
      await info.refresh();
    } catch (e) {
      setError(t(errorKey(e)));
    }
  }

  async function copy() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const d = info.data;
  return (
    <Card title={t("accountPage.gateway")} description={t("accountPage.gatewayDesc")} labelledBy="gateway-title">
      {error && (
        <div className="banner banner--error" role="alert" style={{ marginBottom: 14 }}>
          <span className="banner__body">{error}</span>
        </div>
      )}
      {d && (
        <ul className="plain-list">
          <li>{d.has_token ? t("accountPage.hasToken") : t("accountPage.noToken")}</li>
          {d.legacy_token_active && <li className="tone-gold">{t("accountPage.legacyActive")}</li>}
          {!d.price_feed && <li>{t("accountPage.noPriceFeed")}</li>}
        </ul>
      )}
      {canRotate && (
        <Button variant="secondary" icon={<KeyRound size={14} aria-hidden="true" />} onClick={() => setConfirming(true)}>
          {d?.has_token ? t("accountPage.rotate") : t("accountPage.create")}
        </Button>
      )}

      <Dialog
        open={confirming}
        title={t("accountPage.rotateTitle")}
        description={t("accountPage.rotateDesc")}
        closeLabel={t("dialog.close")}
        onClose={() => setConfirming(false)}
        actions={
          <>
            <Button variant="secondary" data-autofocus onClick={() => setConfirming(false)}>
              {t("dialog.cancel")}
            </Button>
            <Button variant="danger" onClick={() => void rotate()}>
              {t("accountPage.rotateConfirm")}
            </Button>
          </>
        }
      />

      <Dialog
        open={issued !== null}
        title={t("accountPage.issuedTitle")}
        description={t("accountPage.issuedDesc")}
        closeLabel={t("dialog.close")}
        onClose={() => setIssued(null)}
        actions={
          <Button variant="primary" data-autofocus onClick={() => setIssued(null)}>
            {t("accountPage.issuedDone")}
          </Button>
        }
      >
        {issued && (
          <div className="token-box">
            <code className="mono token-box__value" aria-label={t("accountPage.tokenLabel")}>
              {issued.token}
            </code>
            <Button variant="secondary" icon={<Copy size={14} aria-hidden="true" />} onClick={() => void copy()}>
              {copied ? t("accountPage.copied") : t("accountPage.copy")}
            </Button>
          </div>
        )}
      </Dialog>
    </Card>
  );
}
