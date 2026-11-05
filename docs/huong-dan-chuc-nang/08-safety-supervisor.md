# 08 — Safety Supervisor

## Mục đích

Áp dụng chính sách bảo vệ xuyên suốt, độc lập với mô hình và chiến lược. Safety có quyền cao hơn mọi thành phần tạo lệnh.

## Máy trạng thái

| Trạng thái | Lệnh mới | Vị thế đang có | Dùng khi |
| --- | --- | --- | --- |
| `ACTIVE` | Cho phép qua các cổng khác | Giám sát | Điều kiện bình thường |
| `PAUSED` | Chặn | Vẫn giám sát/quản lý bảo vệ | Tin mạnh, spread bất thường, sự cố tạm thời |
| `HALTED` | Chặn | Chỉ thao tác bảo vệ/đóng khẩn theo chính sách | Breach nghiêm trọng, mất đối soát, kill switch |

Chuyển trạng thái phải là event có `reasonCode`, nguồn kích hoạt, thời gian, policy version và actor. Không tự động chuyển từ `HALTED` sang `ACTIVE` nếu chính sách yêu cầu phê duyệt người vận hành.

## Tín hiệu kích hoạt

- Event kinh tế cấp cao, tin bất ngờ, spread/lỗi báo giá, gián đoạn dữ liệu.
- Drawdown/equity/margin vượt ngưỡng; lỗi execution, lệch ledger–MT5, hoặc Guardian EA cảnh báo.
- Manual kill switch qua Dashboard có xác thực và audit.

## Hành động

Chặn intent/execution, hạ confidence hoặc risk budget, hủy lệnh chờ, giảm/đóng vị thế theo policy, thông báo vận hành. Mỗi hành động phải idempotent và xác nhận kết quả từ MT5.

## Kiểm thử

Mô phỏng tin nóng, mất giá, spread rộng, MT5 mất kết nối và breach equity. Xác minh không có lệnh mới sau khi `PAUSED/HALTED` đã được quan sát bởi Execution.
