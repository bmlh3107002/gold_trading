import { WifiOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { GatewayStatus } from "../../api/client";
import { formatDateTime } from "../../lib/format";

/** 1A-C10: MT5 Gateway mất kết nối → băng đỏ trên MỌI trang (thanh bên bị ẩn trên điện thoại).
 * Chưa từng kết nối (NEVER) → không hiện ở đây (trang Tài khoản hướng dẫn). */
export function GatewayBanner({ status }: { status: GatewayStatus | null }) {
  const { t } = useTranslation();
  if (!status || status.state !== "DISCONNECTED") return null;
  const reason = status.reason ?? "NO_HEARTBEAT";
  return (
    <div className="ops-banners">
      <div className="banner banner--error" role="alert">
        <WifiOff size={16} aria-hidden="true" />
        <div className="banner__body">
          <div className="banner__title">{t("gatewayBanner.title")}</div>
          <div>
            {t(`gatewayBanner.reason.${reason}`)}{" "}
            {status.last_seen_at && t("gatewayBanner.lastSeen", { time: formatDateTime(status.last_seen_at) })}
          </div>
          <div>{t("gatewayBanner.impact")}</div>
        </div>
      </div>
    </div>
  );
}
