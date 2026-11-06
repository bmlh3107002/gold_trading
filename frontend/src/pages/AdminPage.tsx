import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError, type Me, type UserCreated } from "../api/client";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Field } from "../components/ui/Field";
import { EmptyState } from "../components/ui/StateView";

const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{2,29}$/;
const MIN_PASSWORD = 12;

interface Props {
  me: Me;
  multiUser: boolean;
  onUserCreated: () => void;
}

/** Trang "Quản trị": chỉ ADMIN. Backend vẫn kiểm lại quyền (403 với người khác). */
export function AdminPage({ me, multiUser, onUserCreated }: Props) {
  const { t } = useTranslation();
  if (!me.is_admin) {
    return (
      <div className="page">
        <Card>
          <EmptyState title={t("adminPage.forbiddenTitle")} description={t("adminPage.forbiddenDesc")} />
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
      <CreateUser multiUser={multiUser} onCreated={onUserCreated} />
    </div>
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

const EMPTY = { username: "", email: "", first_name: "", last_name: "", account_name: "" };

function CreateUser({ multiUser, onCreated }: { multiUser: boolean; onCreated: () => void }) {
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
  const usernameError = touched && !USERNAME_RE.test(username) ? t("adminPage.usernameInvalid") : null;
  const passwordError = touched && password.length < MIN_PASSWORD ? t("adminPage.passwordShort") : null;
  const confirmError = touched && confirm !== password ? t("adminPage.passwordMismatch") : null;
  const filled = username && form.email.trim() && form.first_name.trim() && form.last_name.trim() && password;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (!USERNAME_RE.test(username) || password.length < MIN_PASSWORD || confirm !== password) return;
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const res = await api.createUser({
        username,
        email: form.email.trim(),
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        password,
        account_name: form.account_name.trim() || null,
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
    <Card title={t("adminPage.createTitle")} description={t("adminPage.createDesc")}>
      {!multiUser && (
        <div className="banner banner--warn" role="status" style={{ marginBottom: 14 }}>
          <span className="banner__body">{t("adminPage.errDisabled")}</span>
        </div>
      )}
      {error && (
        <div className="banner banner--error" role="alert" style={{ marginBottom: 14 }}>
          <span className="banner__body">{error}</span>
        </div>
      )}
      {created && (
        <div className="banner banner--info" role="status" style={{ marginBottom: 14 }}>
          <span className="banner__body">
            <strong>{t("adminPage.createdTitle", { username: created.username })}</strong>{" "}
            {t("adminPage.createdDesc", { account: created.account_name })}
          </span>
        </div>
      )}
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
        <Field label={t("adminPage.lastName")} required value={form.last_name} maxLength={64} onChange={set("last_name")} />
        <Field label={t("adminPage.firstName")} required value={form.first_name} maxLength={64} onChange={set("first_name")} />
        <Field
          label={t("adminPage.password")}
          hint={t("adminPage.passwordHint")}
          error={passwordError}
          type="password"
          required
          value={password}
          maxLength={128}
          autoComplete="new-password"
          onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          label={t("adminPage.passwordConfirm")}
          error={confirmError}
          type="password"
          required
          value={confirm}
          maxLength={128}
          autoComplete="new-password"
          onChange={(e) => setConfirm(e.target.value)}
        />
        <Field
          label={t("adminPage.accountName")}
          hint={t("adminPage.accountNameHint")}
          value={form.account_name}
          maxLength={128}
          onChange={set("account_name")}
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
    </Card>
  );
}
