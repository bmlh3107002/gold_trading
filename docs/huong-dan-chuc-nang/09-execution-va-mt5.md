# 09 — Execution, MT5 Gateway và Guardian EA

## Execution Orchestrator

Nhận duy nhất intent đã được Risk duyệt và Safety cho phép. Quản lý vòng đời lệnh bằng finite-state machine, ví dụ:

```text
REQUESTED → VALIDATED → SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED|FILLED
                              ↘ REJECTED|CANCELLED|EXPIRED|UNKNOWN
```

Mỗi thay đổi SL/TP, hủy lệnh hay đóng vị thế là một command riêng có idempotency key, precondition và audit. `UNKNOWN` không được retry mù quáng: phải truy vấn MT5 trước để tránh nhân đôi lệnh.

## Kiểm tra trước gửi

Kiểm lại intent/risk approval còn hạn, Safety, quote freshness, spread, volume step, giá/SL/TP hợp lệ và kết nối MT5. Không dùng cache cũ nếu dữ liệu broker không đáng tin.

## MT5 Gateway

Gateway chạy Python trên Windows gần terminal MT5, cung cấp adapter chuẩn cho lấy quote/account, gửi/sửa/hủy lệnh, đọc deal/vị thế và stream trạng thái. Nó chuyển mã lỗi MT5 thành `reasonCode` chuẩn, giữ map request–ticket/deal và không chứa logic chiến lược.

Yêu cầu độ tin cậy: timeout rõ ràng, reconnect có backoff, heartbeat, hàng đợi bền vững, số dư/position sync sau reconnect và xác thực mTLS/token phù hợp môi trường.

## MT5 + Guardian EA

Guardian EA là hàng rào cuối tại terminal: giám sát ngưỡng equity cứng, điều kiện khẩn cấp và có thể đóng/hạn chế theo chính sách cục bộ nếu dịch vụ phía trên không phản hồi. Quy tắc Guardian phải tối giản, cấu hình được phiên bản hóa và được diễn tập thường xuyên.

## Tiêu chí kiểm thử

- Mất ACK sau khi MT5 đã nhận request không tạo lệnh thứ hai.
- Partial fill, requote, market closed và restart Gateway đều đối soát đúng.
- Guardian có thể thực thi hành động bảo vệ khi control plane mất kết nối.
