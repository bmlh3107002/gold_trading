import {
  Check,
  KeyRound,
  Lock,
  LockOpen,
  Pencil,
  RotateCcw,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  ApiError,
  type GatewayCredential,
  type LiveRequest,
  type Me,
  type UserAdmin,
  type UserCreated,
} from "../api/client";
import { Badge, type BadgeTone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Dialog } from "../components/ui/Dialog";
import { Field } from "../components/ui/Field";
import { SecretBox } from "../components/ui/SecretBox";
import { EmptyState, LoadingState } from "../components/ui/StateView";
import { usePolling } from "../hooks/usePolling";
import { formatDateTime, formatTime } from "../lib/format";

const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{2,29}$/;
const MIN_PASSWORD = 12;

type GatewayState = UserAdmin["gateway_status"];
const GATEWAY_TONE: Record<GatewayState, BadgeTone> = {
  CONNECTED: "profit",
  WAITING: "gold",
  NO_TOKEN: "neutral",
  DISCONNECTED: "loss",
  BLOCKED: "loss",
};

interface Props {
  me: Me;
  multiUser: boolean;
}

/** Trang "Quản trị" (DEC-16, DEC-17): ADMIN quản lý USER (một người một dòng) + cấp token khi
 * USER xin + duyệt bật LIVE. Backend kiểm lại. */
export function AdminPage({ me, multiUser }: Props) {
  const { t } = useTranslation();
  if (!me.is_admin) {
    return (
      <div className="page">
        <Card>
          <EmptyState
            title={t("adminPage.forbiddenTitle")}
            description={t("adminPage.forbiddenDesc")}
          />
        </Card>
      </div>
    );
  }
  return (
    <div className="page" id="admin">
      <div className="page__head">
        <div>
          <h1 className="page__title">{t("adminPage.title")}</h1>
          <p className="page__subtitle">{t("adminPage.subtitle")}</p>
        </div>
      </div>
      <AdminBody multiUser={multiUser} />
    </div>
  );
}

function AdminBody({ multiUser }: { multiUser: boolean }) {
  const users = usePolling(api.users, 15_000, 60_000);
  return (
    <>
      <LiveRequests />
      <UserList
        users={users.data}
        loading={users.loading}
        onChanged={() => void users.refresh()}
      />
      <CreateUser
        multiUser={multiUser}
        onCreated={() => void users.refresh()}
      />
    </>
  );
}

function errorKey(e: unknown) {
  if (!(e instanceof ApiError)) return "errors.server" as const;
  if (e.status === 409) return "adminPage.errExists" as const;
  if (e.status === 422) return "adminPage.errPassword" as const;
  if (e.status === 503) return "adminPage.errKeycloak" as const;
  if (e.kind === "conflict") return "adminPage.errExists" as const;
  return `errors.${e.kind}` as const;
}

function ErrorBanner({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <div
      className="banner banner--error"
      role="alert"
      style={{ marginBottom: 14 }}
    >
      <span className="banner__body">{text}</span>
    </div>
  );
}

// ---------- Danh sách USER (DEC-17: một người một dòng) + sửa / xóa / khóa / token ----------

type Pending =
  | {
      kind: "lock" | "unlock" | "reset" | "token" | "rejectToken" | "delete";
      user: UserAdmin;
    }
  | null;

type Secret =
  | { kind: "password"; username: string; value: string }
  | { kind: "token"; username: string; value: GatewayCredential }
  | null;

function UserList({
  users,
  loading,
  onChanged,
}: {
  users: UserAdmin[] | null;
  loading: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<Pending>(null);
  const [editing, setEditing] = useState<UserAdmin | null>(null);
  const [secret, setSecret] = useState<Secret>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warn, setWarn] = useState<string | null>(null);

  async function confirm() {
    const p = pending;
    if (!p) return;
    setPending(null);
    setBusy(true);
    setError(null);
    setWarn(null);
    try {
      if (p.kind === "lock") {
        const r = await api.lockUser(p.user.sub);
        if (!r.keycloak_synced) setWarn(t("adminPage.lockNotSynced"));
      } else if (p.kind === "unlock") {
        await api.unlockUser(p.user.sub);
      } else if (p.kind === "reset") {
        const r = await api.resetPassword(p.user.sub);
        setSecret({
          kind: "password",
          username: p.user.username,
          value: r.temporary_password,
        });
      } else if (p.kind === "token") {
        const r = await api.issueToken(p.user.sub);
        setSecret({ kind: "token", username: p.user.username, value: r });
      } else if (p.kind === "rejectToken") {
        await api.rejectTokenRequest(p.user.sub);
      } else if (p.kind === "delete") {
        const r = await api.deleteUser(p.user.sub);
        if (!r.keycloak_synced) setWarn(t("adminPage.deleteNotSynced"));
      }
      onChanged();
    } catch (e) {
      setError(
        p.kind === "delete" && e instanceof ApiError && e.status === 409
          ? t("adminPage.deleteConflict")
          : t(errorKey(e)),
      );
    } finally {
      setBusy(false);
    }
  }

  const dialog = pending && {
    title: t(`adminPage.${pending.kind}Title`, {
      username: pending.user.username,
    }),
    // MT-05: mỗi tài khoản ghi giá từ MT5 của mình — khóa một người không làm cả hệ thống ngừng.
    desc: t(`adminPage.${pending.kind}Desc`),
    confirm: t(`adminPage.${pending.kind}Confirm`),
    danger: pending.kind !== "unlock" && pending.kind !== "rejectToken",
  };

  return (
    <Card
      title={t("adminPage.usersTitle")}
      description={t("adminPage.usersDesc")}
      labelledBy="users-title"
    >
      <ErrorBanner text={error} />
      {warn && (
        <div
          className="banner banner--warn"
          role="status"
          style={{ marginBottom: 14 }}
        >
          <span className="banner__body">{warn}</span>
        </div>
      )}
      {!users && loading && <LoadingState label={t("accountPage.loading")} />}
      {users && users.length === 0 && (
        <EmptyState
          title={t("adminPage.noUsers")}
          description={t("adminPage.noUsersDesc")}
        />
      )}
      {users && users.length > 0 && (
        <div
          className="table-wrap"
          tabIndex={0}
          role="region"
          aria-labelledby="users-title"
        >
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("adminPage.colUser")}</th>
                <th scope="col">{t("adminPage.colStatus")}</th>
                <th scope="col">{t("adminPage.colGateway")}</th>
                <th scope="col">{t("adminPage.colLastLogin")}</th>
                <th scope="col">{t("adminPage.colActions")}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const locked = u.status === "LOCKED";
                const requested = u.token_requested_at !== null;
                return (
                  <tr key={u.sub}>
                    <td>
                      {u.display_name || u.username}
                      <div className="header__label">
                        {u.username}
                        {u.email ? ` · ${u.email}` : ""}
                      </div>
                    </td>
                    <td>
                      <Badge tone={locked ? "loss" : "profit"} dot>
                        {t(`adminPage.status.${u.status}`)}
                      </Badge>
                    </td>
                    <td>
                      <Badge tone={GATEWAY_TONE[u.gateway_status]} dot>
                        {t(`adminPage.gateway.${u.gateway_status}`)}
                      </Badge>
                      {requested && (
                        <div style={{ marginTop: 6 }}>
                          <Badge tone="gold">
                            {t("adminPage.tokenRequested", {
                              time: formatDateTime(u.token_requested_at!),
                            })}
                          </Badge>
                        </div>
                      )}
                      {u.gateway_last_seen_at && (
                        <div className="header__label">
                          {t("adminPage.lastSeen", {
                            time: formatDateTime(u.gateway_last_seen_at),
                          })}
                        </div>
                      )}
                      {u.price_feed && (
                        <div className="header__label">
                          {t("adminPage.priceFeedHint")}
                        </div>
                      )}
                    </td>
                    <td className="num">
                      {u.last_login_at
                        ? formatDateTime(u.last_login_at)
                        : t("adminPage.neverLoggedIn")}
                    </td>
                    <td>
                      <div className="admin-actions">
                        <Button
                          variant={requested ? "primary" : "secondary"}
                          icon={<KeyRound size={14} aria-hidden="true" />}
                          disabled={busy || locked}
                          onClick={() => setPending({ kind: "token", user: u })}
                        >
                          {t("adminPage.tokenAction")}
                        </Button>
                        {requested && (
                          <Button
                            variant="secondary"
                            icon={<X size={14} aria-hidden="true" />}
                            disabled={busy}
                            onClick={() =>
                              setPending({ kind: "rejectToken", user: u })
                            }
                          >
                            {t("adminPage.rejectTokenAction")}
                          </Button>
                        )}
                        <Button
                          variant="secondary"
                          icon={<Pencil size={14} aria-hidden="true" />}
                          disabled={busy}
                          onClick={() => setEditing(u)}
                        >
                          {t("adminPage.editAction")}
                        </Button>
                        {locked ? (
                          <Button
                            variant="secondary"
                            icon={<LockOpen size={14} aria-hidden="true" />}
                            disabled={busy}
                            onClick={() =>
                              setPending({ kind: "unlock", user: u })
                            }
                          >
                            {t("adminPage.unlockAction")}
                          </Button>
                        ) : (
                          <Button
                            variant="danger"
                            icon={<Lock size={14} aria-hidden="true" />}
                            disabled={busy}
                            onClick={() => setPending({ kind: "lock", user: u })}
                          >
                            {t("adminPage.lockAction")}
                          </Button>
                        )}
                        <Button
                          variant="secondary"
                          icon={<RotateCcw size={14} aria-hidden="true" />}
                          disabled={busy}
                          onClick={() => setPending({ kind: "reset", user: u })}
                        >
                          {t("adminPage.resetAction")}
                        </Button>
                        <Button
                          variant="danger"
                          icon={<Trash2 size={14} aria-hidden="true" />}
                          disabled={busy || u.price_feed}
                          title={
                            u.price_feed
                              ? t("adminPage.deletePriceFeed")
                              : undefined
                          }
                          onClick={() => setPending({ kind: "delete", user: u })}
                        >
                          {t("adminPage.deleteAction")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Dialog
        open={dialog !== null}
        title={dialog?.title ?? ""}
        description={dialog?.desc}
        closeLabel={t("dialog.close")}
        onClose={() => setPending(null)}
        actions={
          <>
            <Button
              variant="secondary"
              data-autofocus
              onClick={() => setPending(null)}
            >
              {t("dialog.cancel")}
            </Button>
            <Button
              variant={dialog?.danger ? "danger" : "primary"}
              onClick={() => void confirm()}
            >
              {dialog?.confirm}
            </Button>
          </>
        }
      />

      <EditUser
        user={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          onChanged();
        }}
      />

      <Dialog
        open={secret !== null}
        title={
          secret?.kind === "token"
            ? t("adminPage.tokenIssuedTitle", { username: secret.username })
            : t("adminPage.passwordIssuedTitle", {
                username: secret?.username ?? "",
              })
        }
        description={
          secret?.kind === "token"
            ? t("adminPage.tokenIssuedDesc")
            : t("adminPage.passwordIssuedDesc")
        }
        closeLabel={t("dialog.close")}
        onClose={() => setSecret(null)}
        actions={
          <Button
            variant="primary"
            data-autofocus
            onClick={() => setSecret(null)}
          >
            {t("accountPage.issuedDone")}
          </Button>
        }
      >
        {secret?.kind === "token" && (
          <SecretBox
            label={t("accountPage.tokenLabel")}
            value={secret.value.token}
          />
        )}
        {secret?.kind === "password" && (
          <SecretBox label={t("adminPage.password")} value={secret.value} />
        )}
      </Dialog>
    </Card>
  );
}

// ---------- Sửa USER (email, họ, tên) ----------

function splitName(u: UserAdmin): { first: string; last: string } {
  // display_name = "<Tên> <Họ>" (cách backend ghép khi tạo/sửa)
  const parts = (u.display_name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { first: "", last: "" };
  if (parts.length === 1) return { first: parts[0], last: "" };
  return { first: parts.slice(0, -1).join(" "), last: parts[parts.length - 1] };
}

function EditUser({
  user,
  onClose,
  onSaved,
}: {
  user: UserAdmin | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState({ email: "", first_name: "", last_name: "" });
  const [forSub, setForSub] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Nạp lại form mỗi khi mở cho một người khác
  if (user && forSub !== user.sub) {
    const n = splitName(user);
    setForSub(user.sub);
    setForm({ email: user.email ?? "", first_name: n.first, last_name: n.last });
    setError(null);
  }
  if (!user && forSub !== null) setForSub(null);

  const filled =
    form.email.trim() && form.first_name.trim() && form.last_name.trim();

  async function save() {
    if (!user || !filled) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateUser(user.sub, {
        email: form.email.trim(),
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
      });
      onSaved();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? t("adminPage.errEmailExists")
          : e instanceof ApiError && e.status === 422
            ? t("errors.validation")
            : t(errorKey(e)),
      );
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <Dialog
      open={user !== null}
      title={t("adminPage.editTitle", { username: user?.username ?? "" })}
      description={t("adminPage.editDesc")}
      closeLabel={t("dialog.close")}
      onClose={onClose}
      actions={
        <>
          <Button variant="secondary" data-autofocus onClick={onClose}>
            {t("dialog.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy || !filled}
            onClick={() => void save()}
          >
            {t("adminPage.editSave")}
          </Button>
        </>
      }
    >
      <ErrorBanner text={error} />
      <div className="form-grid">
        <Field
          label={t("adminPage.email")}
          type="email"
          required
          value={form.email}
          maxLength={256}
          autoComplete="off"
          onChange={set("email")}
        />
        <Field
          label={t("adminPage.lastName")}
          required
          value={form.last_name}
          maxLength={64}
          onChange={set("last_name")}
        />
        <Field
          label={t("adminPage.firstName")}
          required
          value={form.first_name}
          maxLength={64}
          onChange={set("first_name")}
        />
      </div>
    </Dialog>
  );
}

// ---------- Tạo USER ----------

const EMPTY = {
  username: "",
  email: "",
  first_name: "",
  last_name: "",
};

function CreateUser({
  multiUser,
  onCreated,
}: {
  multiUser: boolean;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState(EMPTY);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<UserCreated | null>(null);
  const [touched, setTouched] = useState(false);

  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const username = form.username.trim();
  // Mật khẩu tạm không bắt buộc: bỏ trống → hệ thống tự sinh và hiện một lần.
  const usernameError =
    touched && !USERNAME_RE.test(username)
      ? t("adminPage.usernameInvalid")
      : null;
  const passwordError =
    touched && password.length > 0 && password.length < MIN_PASSWORD
      ? t("adminPage.passwordShort")
      : null;
  const confirmError =
    touched && confirm !== password ? t("adminPage.passwordMismatch") : null;
  const filled =
    username &&
    form.email.trim() &&
    form.first_name.trim() &&
    form.last_name.trim();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (
      !USERNAME_RE.test(username) ||
      (password && password.length < MIN_PASSWORD) ||
      confirm !== password
    )
      return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.createUser({
        username,
        email: form.email.trim(),
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        password: password || null,
      });
      setCreated(res);
      setForm(EMPTY);
      setTouched(false);
      onCreated();
    } catch (err) {
      setError(t(errorKey(err)));
    } finally {
      // Không giữ mật khẩu trong bộ nhớ trang lâu hơn cần thiết
      setPassword("");
      setConfirm("");
      setBusy(false);
    }
  }

  return (
    <Card
      title={t("adminPage.createTitle")}
      description={t("adminPage.createDesc")}
    >
      {!multiUser && (
        <div
          className="banner banner--warn"
          role="status"
          style={{ marginBottom: 14 }}
        >
          <span className="banner__body">{t("adminPage.errDisabled")}</span>
        </div>
      )}
      <ErrorBanner text={error} />
      <form className="form-grid" onSubmit={(e) => void submit(e)} noValidate>
        <Field
          label={t("adminPage.username")}
          hint={t("adminPage.usernameHint")}
          error={usernameError}
          required
          value={form.username}
          maxLength={30}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          onChange={set("username")}
        />
        <Field
          label={t("adminPage.email")}
          type="email"
          required
          value={form.email}
          maxLength={256}
          autoComplete="off"
          onChange={set("email")}
        />
        <Field
          label={t("adminPage.lastName")}
          required
          value={form.last_name}
          maxLength={64}
          onChange={set("last_name")}
        />
        <Field
          label={t("adminPage.firstName")}
          required
          value={form.first_name}
          maxLength={64}
          onChange={set("first_name")}
        />
        <Field
          label={t("adminPage.password")}
          hint={t("adminPage.passwordHint")}
          error={passwordError}
          type="password"
          value={password}
          maxLength={128}
          autoComplete="new-password"
          onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          label={t("adminPage.passwordConfirm")}
          error={confirmError}
          type="password"
          value={confirm}
          maxLength={128}
          autoComplete="new-password"
          onChange={(e) => setConfirm(e.target.value)}
        />
        <div>
          <Button
            type="submit"
            variant="primary"
            disabled={busy || !multiUser || !filled}
            icon={<UserPlus size={14} aria-hidden="true" />}
          >
            {busy ? t("adminPage.creating") : t("adminPage.create")}
          </Button>
        </div>
      </form>

      <Dialog
        open={created !== null}
        title={t("adminPage.createdTitle", {
          username: created?.username ?? "",
        })}
        description={
          created?.temporary_password
            ? `${t("adminPage.createdDesc")} ${t("adminPage.createdPasswordDesc")}`
            : t("adminPage.createdDesc")
        }
        closeLabel={t("dialog.close")}
        onClose={() => setCreated(null)}
        actions={
          <Button
            variant="primary"
            data-autofocus
            onClick={() => setCreated(null)}
          >
            {t("accountPage.issuedDone")}
          </Button>
        }
      >
        {created?.temporary_password && (
          <SecretBox
            label={t("adminPage.password")}
            value={created.temporary_password}
          />
        )}
      </Dialog>
    </Card>
  );
}

// ---------- Duyệt / từ chối bật LIVE ----------

function LiveRequests() {
  const { t } = useTranslation();
  const live = usePolling(api.adminLiveRequests, 10_000, 30_000);
  const [pending, setPending] = useState<{
    kind: "approve" | "reject";
    req: LiveRequest;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const items = live.data ?? [];
  if (items.length === 0 && !error) return null;

  async function confirm() {
    const p = pending;
    setPending(null);
    if (!p) return;
    setError(null);
    try {
      if (p.kind === "approve") await api.approveLive(p.req.request_id);
      else await api.rejectLive(p.req.request_id);
    } catch (e) {
      setError(
        e instanceof ApiError && e.kind === "conflict"
          ? t("adminPage.liveConflict")
          : t(errorKey(e)),
      );
    }
    await live.refresh();
  }

  return (
    <Card
      title={t("adminPage.liveTitle")}
      description={t("adminPage.liveDesc")}
    >
      <ErrorBanner text={error} />
      {items.map((r) => (
        <div
          key={r.request_id}
          className="banner banner--warn"
          role="status"
          style={{ marginBottom: 10 }}
        >
          <span className="banner__body">
            {t("adminPage.liveItem", {
              name: r.requested_by,
              account: r.account_name,
              time: formatTime(new Date(r.expires_at)),
            })}
          </span>
          <Button
            variant="danger"
            icon={<Check size={14} aria-hidden="true" />}
            onClick={() => setPending({ kind: "approve", req: r })}
          >
            {t("adminPage.liveApprove")}
          </Button>
          <Button
            variant="secondary"
            icon={<X size={14} aria-hidden="true" />}
            onClick={() => setPending({ kind: "reject", req: r })}
          >
            {t("adminPage.liveReject")}
          </Button>
        </div>
      ))}
      <Dialog
        open={pending !== null}
        title={
          pending?.kind === "approve"
            ? t("adminPage.liveApproveTitle", {
                account: pending.req.account_name,
              })
            : t("adminPage.liveRejectTitle")
        }
        description={
          pending?.kind === "approve"
            ? t("adminPage.liveApproveDesc")
            : undefined
        }
        closeLabel={t("dialog.close")}
        onClose={() => setPending(null)}
        actions={
          <>
            <Button
              variant="secondary"
              data-autofocus
              onClick={() => setPending(null)}
            >
              {t("dialog.cancel")}
            </Button>
            <Button
              variant={pending?.kind === "approve" ? "danger" : "primary"}
              onClick={() => void confirm()}
            >
              {pending?.kind === "approve"
                ? t("adminPage.liveApprove")
                : t("adminPage.liveReject")}
            </Button>
          </>
        }
      />
    </Card>
  );
}
