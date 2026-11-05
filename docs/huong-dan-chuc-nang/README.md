# Hướng dẫn chức năng — Gold Trading AI

Thư mục này là đặc tả chức năng được suy ra từ hai sơ đồ trong `docs/mo-hinh/`. Nó là tài liệu thiết kế, **không phải cam kết rằng các thành phần đã được triển khai**.

## Mục tiêu và nguyên tắc

Hệ thống tạo và thực thi giao dịch vàng thông qua các lớp tách biệt: thu thập dữ liệu → phân tích thị trường → chiến lược → kiểm soát rủi ro → thực thi → giám sát. Quyền mở lệnh chỉ tồn tại khi mọi lớp an toàn đều cho phép.

1. Mọi dữ liệu và quyết định phải truy vết được bằng thời gian, nguồn và phiên bản.
2. Không dùng dữ liệu xuất hiện sau thời điểm ra quyết định (point-in-time).
3. Không có `MarketView` hợp lệ thì không tạo tín hiệu; không có phê duyệt rủi ro thì không gửi lệnh.
4. Chế độ LIVE bị khóa mặc định; Safety Supervisor và Guardian EA có quyền chặn cao nhất.

## Chỉ mục

| Tài liệu | Phạm vi |
| --- | --- |
| [01-kien-truc-tong-quan.md](01-kien-truc-tong-quan.md) | Luồng đầu-cuối và ranh giới trách nhiệm |
| [02-du-lieu-va-ingestion.md](02-du-lieu-va-ingestion.md) | Nguồn dữ liệu, chuẩn hóa, lưu point-in-time |
| [03-event-orchestrator.md](03-event-orchestrator.md) | Điều phối sự kiện và job phân tích |
| [04-cac-analyst.md](04-cac-analyst.md) | Sáu analyst độc lập |
| [05-snapshot-fusion-marketview.md](05-snapshot-fusion-marketview.md) | Snapshot, chất lượng dữ liệu, fusion, MarketView |
| [06-strategy-engine.md](06-strategy-engine.md) | Sinh TradeIntent |
| [07-risk-engine-va-ledger.md](07-risk-engine-va-ledger.md) | Phê duyệt, giữ chỗ rủi ro, đối soát |
| [08-safety-supervisor.md](08-safety-supervisor.md) | Máy trạng thái an toàn và emergency stop |
| [09-execution-va-mt5.md](09-execution-va-mt5.md) | Vòng đời lệnh, MT5 Gateway, Guardian EA |
| [10-position-performance.md](10-position-performance.md) | Quản lý vị thế và phản hồi hiệu năng |
| [11-training-model-governance.md](11-training-model-governance.md) | Huấn luyện offline và kiểm soát mô hình |
| [12-van-hanh-kiem-thu.md](12-van-hanh-kiem-thu.md) | Dashboard, mode manager, backtest và runbook |

## Quy ước dữ liệu dùng chung

- Mọi bản ghi có `eventTime` (thời điểm ngoài đời xảy ra) và `ingestedAt` (thời điểm hệ thống biết được). Quyết định tại `decisionAt` chỉ đọc bản ghi có `ingestedAt <= decisionAt`.
- Mọi output phân tích phải có `asOf`, `expiresAt`, `sourceStatus`, `qualityFlags`, `modelVersion` (nếu có) và định danh truy vết.
- Thời gian dùng UTC trong lưu trữ và API. Chỉ đổi múi giờ ở giao diện.
- Các enum khuyến nghị: `sourceStatus = HEALTHY|STALE|MISSING|INVALID`; `qualityFlags` là tập cờ; không dùng chuỗi tự do để biểu đạt trạng thái an toàn.

## Lưu ý an toàn

Tài liệu mô tả cơ chế phần mềm, không phải khuyến nghị đầu tư. Trước khi bật LIVE, phải hoàn thành backtest có chi phí thực tế, kiểm thử paper/shadow, giới hạn rủi ro đã được duyệt và quy trình dừng khẩn cấp.
