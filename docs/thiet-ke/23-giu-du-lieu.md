# Thiết kế — Giữ dữ liệu + dung lượng (GĐ1 bước 10f — ING-33) và replay mọi nguồn (ING-34)

> Tạo 2026-11-13. Code: `backend/src/gold_trading/ops/storage_report.py`, lệnh `cli dung-luong`; test `tests/test_storage_report.py`, `tests/test_replay.py`.

## 1. Đo trước, quyết sau (ING-33)

Không đoán dung lượng: lệnh **chỉ đọc** đo trên DB thật của máy người dùng.

```
docker compose exec backend python -m gold_trading.ingestion.cli dung-luong
```

| Cột | Cách tính |
| --- | --- |
| Số dòng, Dung lượng | `count(*)`; Postgres: `hypertable_size` (TimescaleDB, gồm mọi chunk) hoặc `pg_total_relation_size` (gồm chỉ mục) |
| B/dòng | dung lượng / số dòng — bảng nhỏ bị **thổi cao** (trang 8 KB cố định) → ước tính là **trần trên**, an toàn |
| Dòng/ngày | dữ liệu đủ 7 ngày → số dòng mới 7 ngày / 7; đủ 1 ngày → số dòng mới 24 giờ; chưa đủ 1 ngày → **không ước tính** ("—") |
| Sau 1 năm | (dòng hiện có + dòng/ngày × 365) × B/dòng; `quote_seconds` có hạn giữ (`GT_QUOTE_RETENTION_DAYS`, mặc định 30) → trần = dòng/ngày × hạn giữ × B/dòng |

Bảng đo: `candles`, `quote_seconds`, `candle_quarantine`, `analyst_outputs`, `external_records`, `external_quarantine`, `external_source_checks`, `audit_log` (bảng chưa có → bỏ qua) + dung lượng cả DB.

## 2. Chính sách giữ dữ liệu — hiện hành + đề xuất

**Hiện hành (không đổi trong 10f):**

- Mọi bảng **chỉ thêm, giữ vĩnh viễn** (trigger chặn UPDATE / DELETE) — cần cho point-in-time, backtest, kiểm toán.
- Ngoại lệ duy nhất: `quote_seconds` (giá theo giây) xóa dòng cũ hơn `GT_QUOTE_RETENTION_DAYS` (mặc định 30 ngày, ING-08). Nến M15 vẫn giữ vĩnh viễn.
- Sao lưu tự động 24 giờ / lần, giữ 14 bản (GĐ0).

**Đề xuất** (chốt sau khi có số đo thật trên máy người dùng — mục 20 file kế hoạch): nếu ước tính 1 năm của các bảng chỉ-thêm (trừ `quote_seconds`) nhỏ so với ổ đĩa (vài trăm MB), **giữ nguyên chính sách hiện hành** — không thêm ngoại lệ xóa nào (xóa làm mất khả năng tái lập quá khứ). Chỉ cân nhắc hạn giữ cho `external_source_checks` (nhật ký lần kiểm, ~400 dòng/ngày, chỉ dùng tính trạng thái) nếu số đo cho thấy đáng kể; khi đó hạn giữ phải dài hơn mọi TTL (≥ 400 ngày… hoặc gộp) và ghi thành ngoại lệ có lý do như `quote_seconds`.

## 3. Replay mọi nguồn (ING-34)

`tests/test_replay.py` chạy **mọi việc** của bộ chạy tự động (lịch FOMC / BEA / DOL, số BEA / DOL, H.15, COT, 3 nguồn tin — 10 việc) trên dữ liệu thật đã lưu trong `tests/fixtures`:

1. Chạy lại (2 giờ sau, 3 ngày sau) → 0 thêm, 0 xung đột, 0 hỏng; ảnh chụp mọi revision + số cách ly không đổi.
2. Store mới cùng giờ → y hệt từng revision (nội dung, `event_time`, `available_at`, `ingested_at`, fingerprint); bộ nhớ = SQLite.
3. Đảo thứ tự chạy (số trước lịch) rồi chạy lại đúng thứ tự → cùng tập dữ kiện, cùng số, cùng thời điểm, cùng revision. **Khác biệt duy nhất được chấp nhận:** số DOL nạp khi lịch chưa có mang cờ cảnh báo `RELEASE_OFF_SCHEDULE` — cờ ghi điều hệ thống biết lúc nạp (point-in-time), không viết lại về sau. Chạy thật không xảy ra (lịch DOL theo quy tắc, không gọi mạng, luôn chạy trước số).
4. Fed chết giữa chừng rồi sống lại → kết quả như chạy liền mạch (trừ `ingested_at`).

Nến CSV / MT5: idempotent đã có test riêng (`test_candles.py`, `test_ingest_api.py`).

**Soát lại** (Postgres 16 thật): 10 việc → 215 revision; chạy lại 5 giờ sau không thêm; ảnh chụp Postgres = bộ nhớ.
