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

**Số đo trên máy người dùng (2026-11-13, sau ~6 ngày chạy MT5, 1 ngày giá theo giây):** cả DB 43,7 MB.

| Bảng | Số dòng | Dung lượng | Dòng/ngày | Ước tính 1 năm |
| --- | --- | --- | --- | --- |
| `candles` | 47.760 | 16,8 MB | 697 | 106,3 MB |
| `quote_seconds` (giữ 30 ngày) | 57.363 | 14,9 MB | 52.109 | 406,7 MB (trần, không tăng thêm) |
| `analyst_outputs` | 87 | 344 KB | 63 | ≤ 89,1 MB (bảng nhỏ → B/dòng bị thổi cao) |
| `audit_log` | 133 | 128 KB | 35 | 12,1 MB |
| `external_records` / `external_source_checks` / `candle_quarantine` | 215 / 22 / 32 | 408 / 40 / 64 KB | chưa đủ 1 ngày | — (nhỏ) |
| **Tổng** | | **43,7 MB** | | **≈ 0,6 GB** (trần trên) |

Sao lưu tự động giữ 14 bản → thư mục sao lưu có thể vài GB sau 1 năm (vẫn nhỏ so với ổ đĩa thường).

**Quyết định (người dùng 2026-11-13): giữ nguyên chính sách hiện hành** — mọi bảng chỉ thêm, giữ vĩnh viễn; riêng `quote_seconds` giữ `GT_QUOTE_RETENTION_DAYS` (30 ngày). Không thêm ngoại lệ xóa. Đo lại sau ≥ 7 ngày chạy (tốc độ tăng lịch / tin / nhật ký lần kiểm); xem lại nếu ước tính 1 năm vượt vài GB.

**Đề xuất ban đầu** (trước số đo): nếu ước tính 1 năm của các bảng chỉ-thêm (trừ `quote_seconds`) nhỏ so với ổ đĩa (vài trăm MB), **giữ nguyên chính sách hiện hành** — không thêm ngoại lệ xóa nào (xóa làm mất khả năng tái lập quá khứ). Chỉ cân nhắc hạn giữ cho `external_source_checks` (nhật ký lần kiểm, ~400 dòng/ngày, chỉ dùng tính trạng thái) nếu số đo cho thấy đáng kể; khi đó hạn giữ phải dài hơn mọi TTL (≥ 400 ngày… hoặc gộp) và ghi thành ngoại lệ có lý do như `quote_seconds`.

## 3. Replay mọi nguồn (ING-34)

`tests/test_replay.py` chạy **mọi việc** của bộ chạy tự động (lịch FOMC / BEA / DOL, số BEA / DOL, H.15, COT, 3 nguồn tin — 10 việc) trên dữ liệu thật đã lưu trong `tests/fixtures`:

1. Chạy lại (2 giờ sau, 3 ngày sau) → 0 thêm, 0 xung đột, 0 hỏng; ảnh chụp mọi revision + số cách ly không đổi.
2. Store mới cùng giờ → y hệt từng revision (nội dung, `event_time`, `available_at`, `ingested_at`, fingerprint); bộ nhớ = SQLite.
3. Đảo thứ tự chạy (số trước lịch) rồi chạy lại đúng thứ tự → cùng tập dữ kiện, cùng số, cùng thời điểm, cùng revision. **Khác biệt duy nhất được chấp nhận:** số DOL nạp khi lịch chưa có mang cờ cảnh báo `RELEASE_OFF_SCHEDULE` — cờ ghi điều hệ thống biết lúc nạp (point-in-time), không viết lại về sau. Chạy thật không xảy ra (lịch DOL theo quy tắc, không gọi mạng, luôn chạy trước số).
4. Fed chết giữa chừng rồi sống lại → kết quả như chạy liền mạch (trừ `ingested_at`).

Nến CSV / MT5: idempotent đã có test riêng (`test_candles.py`, `test_ingest_api.py`).

**Soát lại** (Postgres 16 thật): 10 việc → 215 revision; chạy lại 5 giờ sau không thêm; ảnh chụp Postgres = bộ nhớ.

## 6. Spread theo phút, giữ vĩnh viễn (ING-35, KN-03 — người dùng duyệt 2026-11-15)

**Lý do đổi quyết định 2026-11-13:** đánh giá độc lập (`docs/danh-gia/danh-gia-GD0-GD4.md`, F-04) — backtest GĐ6 cần spread **thật** theo giờ và quanh giờ ra tin; giá theo giây xóa sau 30 ngày nên mất vĩnh viễn. Người dùng chọn giữ thống kê theo phút; **giá theo giây vẫn xóa sau `GT_QUOTE_RETENTION_DAYS`** như cũ.

- Bảng `quote_minutes` (migration 0021, bảng thường, chỉ-thêm, trigger chặn UPDATE + DELETE). Một dòng = một revision của một phút của một nguồn giá. Phiên bản công thức `quote-minutes-1`.
- Cột: số giây, số tick, bid đầu / cuối, ask cuối, bid thấp nhất, ask cao nhất, spread cuối giây **nhỏ nhất / trung vị**, spread lớn nhất trong giây **p95 (hạng gần nhất, không nội suy) / lớn nhất**, số giây có cờ `WIDE_SPREAD` / `CALENDAR_CLOSED` (phía dùng tự lọc giờ đóng cửa). Đơn vị spread: point. Spread lớn nhất của một giây = max(spread lớn nhất khai, spread cuối giây) — không bao giờ báo thấp hơn thực tế (Gateway làm tròn lệch ≤ 1 point).
- Chỉ tổng hợp phút đã kết thúc ≥ 10 phút. Phút không có giây → **không có dòng** (không phải spread 0).
- Giây tới muộn → **revision mới**, `available_at` = lúc ghi (đọc point-in-time: `query(..., as_of)`). Bản tính lại có **ít giây hơn** bản đã lưu (giây đã bị xóa theo hạn giữ) → không ghi.
- Bộ chạy nền (`market/quote_minutes.py`, 5 phút / lần): lần đầu sau khởi động nạp bù toàn bộ giây còn giữ (trừ 2 giờ cũ nhất có thể đang bị xóa dở), sau đó xét lại 2 giờ gần nhất. **Xóa giây chờ bộ tổng hợp:** mốc xóa = min(now − hạn giữ, mốc bộ tổng hợp đã xong); chưa chạy xong lần nào → chưa xóa.
- Dung lượng: ~1.380 dòng / ngày / nguồn giá (23 giờ × 60), vài MB / năm. Lệnh chỉ đọc: `cli spread-phut` (số phút, phút đầu / cuối mỗi nguồn); có trong `cli dung-luong`.
- Kiểm chứng: `tests/test_quote_minutes.py` (tính tay, p95, làm tròn, phút trống, giây tới muộn → revision point-in-time, giây đã xóa không ghi đè, tách nguồn, nạp bù, chốt chặn xóa, CHECK, CLI); Postgres 16: migration lên / xuống, `alembic check` sạch, trigger chặn sửa / xóa, chạy lại không ghi trùng.

