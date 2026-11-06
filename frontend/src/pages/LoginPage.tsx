import { LogIn } from "lucide-react";
import { useTranslation } from "react-i18next";
import { loginUrl } from "../api/client";
import { Logo } from "../components/layout/Logo";
import { Button } from "../components/ui/Button";

const KNOWN_ERRORS = ["denied", "state", "expired", "clock", "unavailable", "invalid"] as const;

/** Màn hình khi chưa đăng nhập. Không có ô mật khẩu ở đây: mật khẩu chỉ nhập trên trang Keycloak. */
export function LoginPage() {
  const { t } = useTranslation();
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("auth_error");
  const code = KNOWN_ERRORS.find((k) => k === raw) ?? (raw ? "invalid" : null);

  function login() {
    window.location.assign(loginUrl(window.location.pathname + window.location.hash));
  }

  return (
    <div className="login">
      <div className="login__card">
        <Logo />
        <h1 className="login__title">{t("auth.title")}</h1>
        <p className="login__desc">{t("auth.desc")}</p>
        {code && (
          <div className="banner banner--error" role="alert">
            <span className="banner__body">{t(`auth.error.${code}`)}</span>
          </div>
        )}
        <Button variant="primary" icon={<LogIn size={16} aria-hidden="true" />} onClick={login}>
          {t("auth.login")}
        </Button>
      </div>
    </div>
  );
}
