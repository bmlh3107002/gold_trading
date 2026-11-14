import { ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AccountStatus } from "../../api/client";
import vi from "../../i18n/vi";
import { formatDateTime } from "../../lib/format";

type Reason = keyof typeof vi.entryBlock.reason;

/** GĐ2 4d (DEC-20 câu 5): băng "Đang chặn mở lệnh mới … (tới …)" — một dòng cho mỗi cửa sổ gộp. */
export function EntryBlockBanner({ status }: { status: AccountStatus }) {
  const { t } = useTranslation();
  const windows = status.entry_block_windows ?? [];
  if (windows.length === 0) return null;
  const label = (code: string) =>
    code in vi.entryBlock.reason
      ? t(`entryBlock.reason.${code as Reason}`)
      : t("entryBlock.reasonUnknown", { code });
  return (
    <div className="banner banner--error" role="alert" data-testid="entry-block-banner">
      <ShieldAlert size={16} className="tone-loss" aria-hidden="true" />
      <div className="banner__body">
        <div className="banner__title">{t("entryBlock.title")}</div>
        {windows.map((w) => (
          <div key={`${w.start_at}-${w.end_at ?? "open"}`}>
            {w.reason_codes.map(label).join(" · ")} —{" "}
            {w.end_at ? t("entryBlock.until", { time: formatDateTime(w.end_at) }) : t("entryBlock.untilCleared")}
          </div>
        ))}
        <div className="tone-neutral">{t("entryBlock.note")}</div>
      </div>
    </div>
  );
}
