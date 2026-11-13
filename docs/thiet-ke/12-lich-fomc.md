# Thiết kế — Lịch FOMC từ trang Fed (GĐ1 bước 8b, ING-09)

> Tạo 2026-11-13. Nguồn lịch đầu tiên đi qua khung nguồn ngoài (`10-nguon-ngoai.md`: point-in-time, trạng thái nguồn, khóa, điều khoản). Điều khoản Fed: `VERIFIED` — nội dung Board là public domain, **ghi nguồn Federal Reserve Board** (`11-dieu-khoan-nguon.md#fed`). Code: `backend/src/gold_trading/ingestion/sources/fed_fomc.py`, `ingestion/calendar_sync.py`.

## 1. Lấy từ đâu

| Trang | Cho biết | Ghi chú |
| --- | --- | --- |
| `/monetarypolicy/fomccalendars.htm` | **Ngày họp** mọi năm (đã có cả 2027), dấu `*` = có dự báo kinh tế (SEP), ghi chú (bỏ phiếu văn bản, "Monetary Policy Strategy Meeting") | Không có giờ. Fed ghi: *"Each meeting date is tentative until confirmed at the meeting immediately preceding it."* |
| `/newsevents/calendar.htm` | Danh sách đường dẫn lịch tháng | Tên không đều (`2026-04.htm`, `2026-august.htm`) → lấy đường dẫn từ trang, **không tự dựng** |
| Lịch tháng `/newsevents/<tháng>.htm` | **Giờ công bố** (giờ miền Đông Mỹ): tuyên bố sau họp ("FOMC Meeting"), họp báo, biên bản | Chỉ có tới khoảng 1–2 tháng tới (13/11/2026: tới hết 12/2026) |

Mỗi lần chạy tải: trang lịch họp + trang danh sách + lịch tháng từ **tháng trước** tới tháng xa nhất Fed đã đăng (khoảng 3–5 trang). Giới hạn 5 MB/trang, chỉ chấp nhận `www.federalreserve.gov` (chuyển hướng sang nơi khác → lỗi), mã lỗi ngắn (ING-31).

## 2. Sự kiện ghi vào `external_records` (`kind = calendar`, `source = fed_fomc`)

| `logical_key` | `event_time` (UTC) |
| --- | --- |
| `FOMC_STATEMENT:<ngày cuối họp>` | Giờ tuyên bố trên lịch tháng; **chưa có → 00:00 giờ miền Đông của ngày cuối họp**, `time_confirmed = false`, `all_day = true` |
| `FOMC_PRESS_CONFERENCE:<ngày>` | Giờ trên lịch tháng |
| `FOMC_MINUTES:<ngày công bố>` | Giờ trên lịch tháng; `meeting_end` = cuộc họp được nói tới |

Payload: `meeting_start/end`, `sep`, `note`, `tentative`, `time_confirmed`, `all_day`, `release_local`, `tz = America/New_York`, `status` (`SCHEDULED` / `REMOVED`), `flags`. Chỉ giữ sự kiện từ 7 ngày trước trở đi.

**Quyết định an toàn:**
- **Không tự gán "2 giờ chiều như mọi khi"** cho cuộc họp chưa có trên lịch tháng (dù 8/8 cuộc họp 2026 đều 14:00 ET). Phần chặn giao dịch (GĐ sau) phải coi `all_day` là **cả ngày**.
- Lịch tháng và trang lịch họp lệch nhau (ngày tuyên bố ≠ ngày cuối họp, có tuyên bố cho cuộc họp không có trên trang lịch họp) → `CALENDAR_SOURCES_DISAGREE`, **không tin giờ**, vẫn ghi cả hai (thêm sự kiện = hướng chặn nhiều hơn) (1C-C06).
- `tentative = true` khi cuộc họp ngay trước chưa diễn ra (theo câu của Fed ở trên).
- Định dạng lạ ở bất kỳ trang nào (tháng, ngày, giờ, mục FOMC mới, tiêu đề tháng không khớp đường dẫn, không còn cuộc họp tương lai nào) → cả lần tải `INVALID` (`PARSE_ERROR`), **không ghi gì**.

## 3. Đồng bộ theo revision (`calendar_sync.py`, dùng chung cho các nguồn lịch sau)

- Mới → revision 0. Không đổi → bỏ qua (nạp lại → cùng kết quả). Đổi giờ/nội dung → revision mới; trước lúc biết vẫn thấy bản cũ (1C-C03).
- Sự kiện **tương lai** không còn trên trang → revision `status = REMOVED`, không xóa (1C-C02). Quá **2** sự kiện biến mất trong một lần → nghi trang hỏng: không ghi gì, `INVALID` `TOO_MANY_REMOVALS`.
- Trạng thái nguồn (ING-30): `fetch_ttl = 26 giờ` (tải mỗi ngày); không đặt `data_ttl` (lịch).

## 4. Kiểm 2026-11-13 (trang thật)

- Trang lịch họp: 57 cuộc họp 2021–2027 đọc đúng, gồm họp vắt hai tháng (`Apr/May 30-1`), bỏ phiếu văn bản (22/08/2025), họp chiến lược (26–27/10/2027).
- Cả 12 lịch tháng 2026: 8/8 tuyên bố đúng ngày cuối họp, đều 14:00 ET; 8 biên bản trỏ đúng cuộc họp; không cờ lệch. Giờ mùa hè/đông đúng (17/06: 18:00 UTC; 09/12: 19:00 UTC).
- Tải trực tiếp: tuyên bố kế tiếp 09/12/2026 19:00 UTC (đã xác nhận), họp báo 19:30 UTC; các cuộc họp 2027 "chưa có giờ", "dự kiến".

## 5. Chưa làm

Chạy tự động mỗi ngày trong backend + kiểm trên máy người dùng (8g); hiển thị + câu ghi nguồn Fed (DSH-09); mức quan trọng (ING-20); dùng lịch để chặn giao dịch (GĐ sau). Lệnh chạy tay: `docker compose exec backend python -m gold_trading.ingestion.cli fomc` (`--dry-run`: không ghi DB).
