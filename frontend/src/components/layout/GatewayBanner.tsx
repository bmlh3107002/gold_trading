import { Link2Off, Loader2, WifiOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { GatewayStatus } from "../../api/client";
import { formatDateTime } from "../../lib/format";

/** 1A-C10: MT5 Gateway mất kết nối → băng đỏ trên MỌI trang (thanh bên bị ẩn trên điện thoại).
 * Chưa từng kết nối (NEVER) → không hiện ở đây (trang Tài khoản hướng dẫn).
 * Gateway kết nối nhưng liên kết MT5 lệch / chưa xác nhận (MT-13/14) → băng đỏ chỉ cách xử lý:
 * hệ thống KHÔNG ghi giá dù MT5 vẫn chạy (kiểm trên máy 2026-11-12: trước đây chỉ thấy "giá cũ"). */
export function GatewayBanner({ status }: { status: GatewayStatus | null }) {
  const { t } = useTranslation();
  if (!status) return null;
  if (status.state === "CONNECTED") {
    const link = status.link_status;
    if (link !== "MISMATCH" && link !== "PENDING_CONFIRM" && link !== "NONE") return null;
    return (
      <div className="ops-banners">
        <div className="banner banner--error" role="alert">
          <Link2Off size={16} aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t(`gatewayBanner.link.${link}.title`)}</div>
            <div>{t(`gatewayBanner.link.${link}.desc`)}</div>
            <div>
              <a href="#account">{t("gatewayBanner.link.action")}</a>
            </div>
          </div>
        </div>
      </div>
    );
  }
  if (status.state !== "DISCONNECTED") return null;
  const reason = status.reason ?? "NO_HEARTBEAT";
  const starting = reason === "GATEWAY_STARTING";
  // NO_HEARTBEAT: thời điểm tín hiệu cuối; lý do khác: Gateway vẫn gửi nhịp tim → ghi "từ lúc"
  // (mốc bắt đầu mất), không ghi "tín hiệu cuối" (nhảy theo từng nhịp tim).
  const when =
    reason === "NO_HEARTBEAT"
      ? status.last_seen_at && t("gatewayBanner.lastSeen", { time: formatDateTime(status.last_seen_at) })
      : status.reason_since && t("gatewayBanner.since", { time: formatDateTime(status.reason_since) });
  return (
    <div className="ops-banners">
      <div className={`banner ${starting ? "banner--warn" : "banner--error"}`} role="alert">
        {starting ? <Loader2 size={16} aria-hidden="true" /> : <WifiOff size={16} aria-hidden="true" />}
        <div className="banner__body">
          <div className="banner__title">{t(starting ? "gatewayBanner.startingTitle" : "gatewayBanner.title")}</div>
          <div>
            {t(`gatewayBanner.reason.${reason}`)} {when}
          </div>
          <div>{t("gatewayBanner.impact")}</div>
        </div>
      </div>
    </div>
  );
}
