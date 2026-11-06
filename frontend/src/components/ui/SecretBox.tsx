import { Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "./Button";

/** Hiện một bí mật (token, mật khẩu tạm) MỘT LẦN, kèm nút sao chép. Không lưu ở đâu khác. */
export function SecretBox({ value, label }: { value: string; label: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="token-box">
      <span className="header__label">{label}</span>
      <code className="mono token-box__value" aria-label={label}>
        {value}
      </code>
      <Button variant="secondary" icon={<Copy size={14} aria-hidden="true" />} onClick={() => void copy()}>
        {copied ? t("accountPage.copied") : t("accountPage.copy")}
      </Button>
    </div>
  );
}
