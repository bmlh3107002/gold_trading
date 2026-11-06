import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { OpsHealth } from "../../api/client";

/** Cảnh báo vận hành (đồng hồ, ổ đĩa, sao lưu). Không có dữ liệu thì không hiện gì. */
export function OpsBanner({ health }: { health: OpsHealth | null }) {
  const { t } = useTranslation();
  // Dữ liệu sai dạng (ví dụ backend cũ) → không hiện gì, không đoán.
  const c = health?.clock;
  if (!c || typeof c.state !== "string") return null;
  const items: { key: string; text: string; danger: boolean }[] = [];
  if (c.state === "WARN" || c.state === "BLOCKED") {
    items.push({
      key: "clock",
      text: t(c.state === "BLOCKED" ? "ops.clockBlocked" : "ops.clockWarn", {
        offset: c.offset_s == null ? "?" : (c.offset_s > 0 ? "+" : "") + c.offset_s.toFixed(1),
      }),
      danger: c.state === "BLOCKED",
    });
  } else if (c.state === "UNKNOWN" && c.measured_at) {
    items.push({ key: "clock", text: t("ops.clockUnknown"), danger: false });
  }
  for (const d of health.disks ?? []) {
    if (d.warn && d.used_pct != null) {
      items.push({ key: `disk-${d.name}`, text: t(`ops.disk.${d.name}`, { pct: d.used_pct.toFixed(0) }), danger: d.used_pct > 95 });
    }
  }
  const b = health.backup;
  if (b && (b.state === "FAILED" || b.state === "STALE" || b.state === "MISSING")) {
    items.push({ key: "backup", text: t(`ops.backup.${b.state}`), danger: b.state === "FAILED" });
  }
  if (items.length === 0) return null;
  return (
    <div className="ops-banners">
      {items.map((i) => (
        <div key={i.key} className={`banner ${i.danger ? "banner--error" : "banner--warn"}`} role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <span className="banner__body">{i.text}</span>
        </div>
      ))}
    </div>
  );
}
