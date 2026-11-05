# 12 — Vận hành, kiểm thử và Backtest

## Dashboard

Hiển thị trạng thái nguồn, pipeline/job, MarketView, confidence/risk flags, portfolio/equity, order lifecycle, chênh lệch đối soát và Safety. Dashboard không được chỉ là màn hình đẹp: mọi cảnh báo phải liên kết được đến incident/audit log.

## Mode Manager

Các mode khuyến nghị: `BACKTEST`, `PAPER`, `SHADOW`, `LIVE`. `LIVE` mặc định khóa, yêu cầu quyền phù hợp, checklist trước bật và audit hai bước nếu chính sách yêu cầu. Chuyển mode phải không làm mất các lệnh/vị thế đang có và luôn đồng bộ Safety state.

## Backtest

Backtest phải replay theo `ingestedAt`, dùng snapshot và policy/model version lịch sử. Bắt buộc mô phỏng bid/ask spread, slippage, commission/swap, latency, fill một phần, market hours và giới hạn margin. Báo cáo nêu rõ giả định, khoảng dữ liệu, bias còn lại và kết quả theo regime.

## Checklist trước LIVE

- Đối soát MT5 và Risk Ledger sạch; clock/heartbeat/kết nối khỏe.
- Data source bắt buộc healthy; alert, kill switch và Guardian EA đã được kiểm tra.
- Policy/risk limits và model/strategy versions được duyệt; chỉ bật với hạn mức nhỏ/canary.
- Có on-call, runbook incident, quyền dừng khẩn và nhật ký audit hoạt động.

## Kiểm thử hệ thống

Thực hiện unit test cho rule, contract test giữa dịch vụ, replay/integration với MT5 demo, chaos test cho mất mạng/restart/duplicate, và diễn tập kill switch. Các test an toàn phải chạy trước mọi đợt phát hành LIVE.
