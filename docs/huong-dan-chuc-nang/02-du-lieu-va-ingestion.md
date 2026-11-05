# 02 — Dữ liệu và Ingestion

## Mục đích

Thu thập giá, tin tức, lịch kinh tế, dữ liệu vĩ mô và vị thế; chuẩn hóa chúng thành dữ liệu có thể tái dựng đúng tại mọi thời điểm quyết định.

## Nguồn và dữ liệu tối thiểu

| Nguồn | Ví dụ | Trường cốt lõi |
| --- | --- | --- |
| Giá MT5 | OHLC, tick, spread | `symbol`, `timeframe`, `bid`, `ask`, `eventTime` |
| Tin tức | Báo, RSS, phát biểu Fed | `publisher`, `publishedAt`, `body`, `url` |
| Lịch kinh tế | CPI, NFP, FOMC | `country`, `releaseAt`, `actual`, `forecast`, `importance` |
| Vĩ mô/vị thế | DXY, real yield 10Y, COT, ETF flow | `series`, `value`, `periodEnd`, `releaseAt` |

## Xử lý

1. Gán `eventTime`, `ingestedAt`, `source`, khóa định danh và payload gốc bất biến.
2. Kiểm tra schema, đơn vị, timezone, khoảng giá trị và tính mới.
3. Khử trùng lặp theo khóa nguồn hoặc fingerprint nội dung; không ghi đè lịch sử.
4. Chuẩn hóa symbol, đơn vị, tần suất và bản sửa đổi dữ liệu (`revision`).
5. Lưu raw, normalized và chỉ mục point-in-time. Dữ liệu lỗi đi vào quarantine kèm lý do.

## Hợp đồng đầu ra

Mỗi bản ghi normalized có `recordId`, `source`, `eventTime`, `ingestedAt`, `sourceStatus`, `payloadVersion`, `rawRef` và `qualityFlags`. Lớp sau chỉ đọc dữ liệu có `ingestedAt` không muộn hơn thời điểm đánh giá.

## Lỗi và kiểm thử

- Mất nguồn: phát `STALE`/`MISSING`, không bịa giá trị thay thế.
- Dữ liệu đến muộn: vẫn lưu nhưng phải mang `ingestedAt` thực tế để backtest không nhìn trước tương lai.
- Kiểm thử: dedupe, timezone/DST, revision, gap giá, tick đảo thứ tự, restart và replay cùng dữ liệu cho ra cùng kết quả.
