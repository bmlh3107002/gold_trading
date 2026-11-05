# Guardian EA

Hàng rào cuối chạy ngay trong terminal MT5 (docs/09). Hoạt động độc lập với backend: nếu control plane mất kết nối, EA vẫn bảo vệ được tài khoản.

- Equity dưới `MinEquity` hoặc drawdown vượt `MaxDrawdownPct` → hủy lệnh chờ và đóng mọi vị thế có `MagicNumber` của bot.
- Gateway không cập nhật heartbeat (`GT_HEARTBEAT`) quá `HeartbeatTimeoutSec` → chặn. Chỉ đóng vị thế nếu bật `CloseOnHeartbeatLoss`.
- Trạng thái chặn được công bố qua global variable `GT_GUARDIAN_TRIPPED` để Gateway báo cho Safety Supervisor.

> File này **chưa được biên dịch hay kiểm thử**. Phải biên dịch bằng MetaEditor và diễn tập trên tài khoản demo trước khi dùng.
