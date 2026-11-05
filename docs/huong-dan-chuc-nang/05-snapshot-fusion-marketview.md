# 05 — Snapshot, Fusion và MarketView

## Snapshot Builder

Gom các output analyst còn hạn thành một ảnh chụp bất biến tại một thời điểm.

```json
{
  "snapshotId": "...",
  "eventTime": "...", "availableAt": "...", "expiresAt": "...",
  "analystOutputs": ["..."], "qualityFlags": [], "inputManifest": "..."
}
```

`availableAt` là lúc mọi input đã sẵn sàng cho hệ thống, không phải lúc sự kiện diễn ra. Snapshot phải lưu manifest input để tái dựng.

## Data Quality Gate

1. Kiểm tra nguồn bắt buộc theo chế độ và chiến lược.
2. Kiểm tra freshness/TTL, schema, coverage, outlier và xung đột timestamp.
3. Thiếu nguồn bắt buộc: trả `REJECTED`, không tạo tín hiệu.
4. Nguồn tùy chọn cũ/mất: giữ snapshot nhưng gắn cờ và hạ confidence theo chính sách có phiên bản.

Quality Gate không tự chữa dữ liệu. Mọi quyết định degrade phải có lý do và được audit.

## Fusion (meta-model)

Chỉ nhận output còn hiệu lực và đã qua Quality Gate. Kết hợp dự báo, regime, sự đồng thuận/bất đồng, độ mới tin và chất lượng nguồn để tạo bias xác suất. Bất đồng lớn giữa analyst phải giảm confidence; không được lấy đa số đơn thuần khi các nguồn tương quan cao.

## Kiểm soát chất lượng mô hình

Theo dõi calibration, Brier/log loss, PSI/drift, tỷ lệ output bị stale và hiệu năng theo regime. Model mới chạy shadow trước, có ngưỡng rollback và registry lưu version/data range/metrics/approver.

## MarketView

Đầu ra tiêu chuẩn cho các lớp sau:

```json
{
  "marketViewId": "...", "snapshotId": "...", "asOf": "...", "expiresAt": "...",
  "bias": "LONG|SHORT|NEUTRAL", "pUp": 0.0, "pDown": 0.0,
  "confidence": 0.0, "regime": "...", "volForecast": 0.0,
  "drivers": [], "riskFlags": [], "qualityFlags": []
}
```

Khi hết hạn, Orchestrator invalidate MarketView. Strategy phải kiểm tra `expiresAt` tại lúc tạo intent, còn Risk/Execution kiểm tra lại trước gửi lệnh.
