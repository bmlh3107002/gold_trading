# 01 — Kiến trúc tổng quan

## Mục đích

Tách quyết định giao dịch thành các tầng độc lập để một lỗi dữ liệu, mô hình hoặc broker không tự động biến thành giao dịch không kiểm soát.

## Luồng chính

```text
Nguồn dữ liệu → Ingestion/Database → Event Orchestrator → Analyst → Snapshot
→ Quality Gate → Fusion → MarketView → Strategy → Risk Engine → Execution
→ MT5 Gateway → MT5 + Guardian EA
                                      ↘ Safety Supervisor ↗
```

`Performance` nhận kết quả đã đối soát từ `Risk Ledger` để phục vụ theo dõi và huấn luyện offline. `Position Manager` chỉ đề xuất quản lý vị thế; mọi sửa SL/TP vẫn đi qua Execution và các cổng an toàn.

## Ranh giới trách nhiệm

| Lớp | Được làm | Không được làm |
| --- | --- | --- |
| Intelligence | Đọc dữ liệu, tạo `MarketView` | Gửi lệnh tới MT5 |
| Strategy | Tạo `TradeIntent` | Cấp vốn hoặc bỏ qua Safety |
| Risk | Phê duyệt/từ chối và giữ chỗ rủi ro | Tự thay đổi giá thị trường |
| Execution | Chuyển intent đã duyệt thành lệnh idempotent | Tự tăng khối lượng |
| Safety | Chặn/hạn chế/halt | Tạo tín hiệu giao dịch |
| MT5/Guardian | Thực thi và bảo vệ tại điểm cuối | Suy luận chiến lược |

## Bất biến bắt buộc

- Một `TradeIntent` phải gắn `marketViewId`, `riskDecisionId`, `policyVersion` và `correlationId` trước khi gửi broker.
- `Risk Engine` và `Safety Supervisor` có thể từ chối ở bất kỳ thời điểm nào trước gửi lệnh. Guardian EA vẫn có thể đóng khẩn cấp sau gửi lệnh.
- Broker/MT5 là nguồn sự thật cho lệnh khớp, lệnh chờ, vị thế và equity; dữ liệu nội bộ phải được đối soát.
- Các thao tác ghi và side effect phải chịu được gửi lại (idempotent).

## Tiêu chí chấp nhận

Có thể truy xuất từ một deal MT5 về: yêu cầu execution, quyết định risk, TradeIntent, MarketView/snapshot, nguồn dữ liệu và phiên bản mô hình/chính sách.
