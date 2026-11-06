# GĐ8 — Paper trading (đặc tả 08, 09, 10): khớp lệnh giả lập bằng giá sống, chưa gửi MT5

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| EXE-01 | Order FSM | `[x]` | `execution/order_fsm.py` |
| EXE-02 | Execution Orchestrator: chỉ nhận intent đã Risk duyệt + Safety cho phép | `[ ]` | Adapter khớp lệnh **giả lập** |
| EXE-03 | Kiểm tra trước gửi: hạn approval, Safety, quote mới, spread, volume step, SL/TP, độ lệch giá so với lúc nến đóng | `[ ]` | ← ING-08 |
| EXE-04 | Command riêng cho sửa SL/TP, hủy, đóng (idempotency key, precondition, audit) | `[ ]` | |
| SAF-04 | Trigger tự động: dữ liệu STALE / mất Gateway | `[ ]` | |
| SAF-05 | Trigger tự động: tin nóng, sự kiện cấp cao | `[ ]` | ← FAST-03, EVT-02 |
| SAF-06 | Trigger tự động: spread bất thường, equity/drawdown | `[ ]` | |
| PSM-01 | Position Manager đề xuất BE, trailing, time-stop, chốt/giảm (qua Risk/Execution/Safety) | `[ ]` | `position/` |
| PSM-02 | Không nới rủi ro; time-stop theo giờ khớp thật; restart không lặp command | `[ ]` | |
| PRF-01 | Performance: PnL, drawdown, hit rate, expectancy, MAE/MFE, chi phí, slippage | `[ ]` | `performance/` |
| PRF-02 | Tách paper/shadow/live, theo strategy/regime; so với backtest | `[ ]` | |
| DSH-04 | Trang Lệnh & vị thế | `[ ]` | |
| DSH-06 | Trang Nhật ký (audit, incident) | `[ ]` | |
| OPS-09 | Thông báo sự cố (mất MT5, giá cũ, Safety tự dừng) | `[ ]` | |
| OPS-08 | Runbook sự cố bản đầu | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 8-C01 | Safety chuyển PAUSED/HALTED khi đang có lệnh | Không lệnh mới; vị thế chỉ thao tác bảo vệ | `[ ]` |
| 8-C02 | Mất Gateway khi đang có vị thế paper | STALE → PAUSED; vị thế giữ, đánh dấu chưa định giá được | `[ ]` |
| 8-C03 | Restart khi đang có vị thế | Khôi phục đúng, không lặp command | `[ ]` |
| 8-C04 | Gap qua SL (cuối tuần/tin) | Khớp ở giá mở cửa thật, không ở giá SL | `[ ]` |
| 8-C05 | Time-stop, trailing, BE | Đúng quy tắc chiến lược | `[ ]` |
| 8-C06 | Command trùng | Idempotent | `[ ]` |

**Gate GĐ8:** paper chạy ≥ 4 tuần (người dùng có thể đổi số tuần) trên dữ liệu thật; chênh lệch so backtest trong ngưỡng đã đặt; không có sự cố chưa xử lý. Bao gồm MT-16 (paper theo tài khoản, không lệnh khi thiếu liên kết, MT-C09).
