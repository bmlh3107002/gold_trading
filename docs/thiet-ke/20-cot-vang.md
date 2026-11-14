# Thiết kế — COT vàng của CFTC (GĐ1 bước 9e: ING-12, 1F-C01..C03)

> Code: `backend/src/gold_trading/ingestion/sources/cftc_cot.py`. Test: `backend/tests/test_cftc_cot.py` (khối GOLD thật chốt 03/11/2026, `tests/fixtures/cftc/`). Lệnh: `python -m gold_trading.ingestion.cli cot [--dry-run]`. Chạy tự động (`16-…`), nguồn `cftc_cot_gold`.

## 1. Nguồn + điều khoản

- Báo cáo văn bản "CMX (Futures Only)" legacy short format: `www.cftc.gov/dea/futures/deacmxsf.htm`, khối **GOLD – COMMODITY EXCHANGE INC., Code-088691**, hợp đồng 100 troy ounce.
- Điều khoản (`11-dieu-khoan-nguon.md#cftc`, đọc nguyên văn từ máy người dùng): public domain, yêu cầu ghi nguồn CFTC → dòng ghi nguồn ở chân trang web.
- Kiểm từ máy người dùng (2026-11-13): trang báo cáo 200; **API `publicreporting.cftc.gov` 403** → không dùng API. Máy chủ đám mây bị `www.cftc.gov` trả 403 → dữ liệu test là văn bản in ra từ máy người dùng (README fixture).
- Chọn báo cáo **legacy** (không thương mại / thương mại / nhỏ lẻ): định dạng ổn định nhiều năm, có đẳng thức cộng để kiểm. Báo cáo "disaggregated" (Managed Money) chưa dùng — thêm sau nếu GĐ3 cần.

## 2. Point-in-time (1F-C01)

- `event_time` = hết ngày chốt vị thế (thứ Ba) giờ New York.
- `available_at` = **15:30 giờ New York** ngày công bố trong **lịch chính thức** CFTC (trang Release Schedule, nguyên văn: *"released at 3:30 p.m. Eastern time … usually released on Friday … Federal holidays may delay release by one or two days"*). Bảng 2026 chép vào code (`RELEASES`, phiên bản `cftc-cot-schedule-2026.11.13`): 52 lần, 6 lần dời (05/01, 22/06, 06/07, 16/11, 30/11, 28/12). Ngày công bố = ngày đầu tiên trong lịch sau ngày chốt (≤ 8 ngày).
- Ngày chốt không có trong lịch (CFTC mới đăng tới hết 2026) → **không đoán**: `available_at` trống (biết từ lúc tải) + cờ `RELEASE_SCHEDULE_UNKNOWN`. **Việc định kỳ:** khi CFTC đăng lịch 2027 → chép thêm bảng + đổi phiên bản.
- Nạp sớm hơn giờ công bố trên lịch (không thể với trang thật, nhưng phòng hờ) → vẫn không thấy trước 15:30.

## 3. Kiểm tra (sai → `INVALID` cả lần tải, không ghi)

- Đúng **một** khối `GOLD - COMMODITY EXCHANGE INC.` mã `088691` (không nhầm MICRO GOLD 088695); mã đổi / đơn vị khác `(CONTRACTS OF 100 TROY OUNCES)` → dừng (**1F-C03**).
- 9 số vị thế, 9 số thay đổi, 9 tỷ lệ, tổng số trader + 7 số trader; định dạng số `1,234` / `-1,234`.
- **Đẳng thức của CFTC** (kiểm trên số thật 03/11/2026): long không thương mại + spread + long thương mại = tổng long; tương tự short; tổng + nhỏ lẻ = khối lượng mở (cả hai phía); cùng đẳng thức cho dòng thay đổi với "CHANGE IN OPEN INTEREST"; mỗi % lệch số/OI ≤ 0,1.
- Ngày chốt sau `now` → INVALID.
- Cờ (không chặn): ngày chốt không phải thứ Ba `AS_OF_NOT_TUESDAY`; mốc "CHANGES FROM" ≠ chốt − 7 ngày `CHANGE_BASE_NOT_PRIOR_WEEK`.

## 4. Ghi

Khóa `GOLD_088691:<ngày chốt>`, `kind = positioning`. Payload: OI, thay đổi OI, 9 vị thế, 9 thay đổi, %, số trader, `noncomm_net` (long − short không thương mại, thông tin), giờ công bố, phiên bản lịch, cờ. CFTC sửa báo cáo → revision mới (quá khứ giữ); trang trả báo cáo **cũ hơn** báo cáo mới nhất đã có (bộ đệm) → không ghi.

## 5. Lịch tải + trạng thái (1F-C02)

Tải khi lần OK cuối > 6 giờ; lỗi → 30 phút. Giờ "đã biết" lấy từ lịch nên tải muộn vài giờ không làm sai point-in-time. `fetch_ttl` 30 giờ; `data_ttl` **14 ngày** (chốt thứ Ba → công bố thứ Sáu → tuần sau; lễ dời thêm 3 ngày → cũ nhất ~13 ngày) → CFTC trễ (chính phủ đóng cửa) → STALE, không dùng số cũ như số mới.

## 6. Kiểm chứng

Số đọc khớp đọc tay; soát lại: đọc độc lập bằng cách tách cột thô — khớp vị thế, OI, %; bảng lịch: mọi ngày dời có ngày lễ liên bang trong tuần, mọi ngày không dời là thứ Sáu, mọi thứ Ba 2026 có đúng một ngày công bố; chạy qua bộ chạy + Postgres: 1 bản ghi, `available_at` 06/11 20:30 UTC, tải lại không thêm. **Chưa:** tải trực tiếp từ backend trên máy người dùng (mục 17).

## 7. Nạp bù lịch sử (2026-11-14, cho Positioning analyst — GĐ3 bước 5; người dùng yêu cầu)

**Lý do:** Positioning cần ≥ 52 tuần; bộ nạp định kỳ chỉ ghi báo cáo mới nhất (cố ý từ chối báo cáo cũ hơn). Code: `ingestion/sources/cot_backfill.py`; lệnh `python -m gold_trading.ingestion.cli cot-bu [--dry-run] [--years 4] [--file …]`. Test `tests/test_cot_backfill.py`.

- **Nguồn:** file lịch sử năm của CFTC `www.cftc.gov/files/dea/history/deacot<năm>.zip` (legacy, futures only → `annual.txt`, CSV có tiêu đề) — cùng báo cáo với `deacmxsf.htm`, nhà cung cấp `cftc` VERIFIED. Máy chủ đám mây bị 403 → **chưa xem được file thật khi viết code**; chạy trên máy người dùng.
- **An toàn:** đọc cột theo **tên** (chuẩn hóa khoảng trắng / chữ hoa); thiếu cột → dừng và in tên cột thấy được; chỉ mã `088691` + tên GOLD; kiểm đẳng thức CFTC từng tuần (vị thế + thay đổi); ngày trùng trong file / hai file khác số → dừng. **Cổng đối chiếu:** phải có ≥ 1 tuần trùng báo cáo đã lưu từ trang (vd. 03/11/2026) và khớp 100 % OI + 9 vị thế — không thì **không ghi gì**. Chỉ thêm tuần chưa có (cờ `BACKFILL`, `report_source = CFTC_HISTORY_ANNUAL`), không sửa báo cáo đã lưu; "đã biết" = lúc nạp; ngoài lịch 2026 → `RELEASE_SCHEDULE_UNKNOWN`.
- **Còn:** chạy `--dry-run` trên máy người dùng để xác nhận tên cột thật.
