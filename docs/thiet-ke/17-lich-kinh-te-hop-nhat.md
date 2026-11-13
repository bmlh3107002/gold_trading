# Thiết kế — Bảng lịch kinh tế hợp nhất + mức quan trọng có phiên bản (GĐ1 bước 8g-2)

> Code: `backend/src/gold_trading/ingestion/event_importance.py` (chính sách), `ingestion/economic_calendar.py` (bảng hợp nhất), lệnh `python -m gold_trading.ingestion.cli lich --days 14`. Test: `backend/tests/test_economic_calendar.py`. Ảnh hưởng quyết định giao dịch (cửa sổ rủi ro sẽ được Safety / làn nhanh dùng ở GĐ2) → mọi thay đổi ghi ở đây kèm lý do.

## 1. Mức quan trọng (ING-20) — phiên bản `event-policy-2026.11.13`

| Sự kiện | Mức | Lý do |
| --- | --- | --- |
| `FOMC_STATEMENT` | HIGH | quyết định lãi suất của Fed |
| `FOMC_PRESS_CONFERENCE` | HIGH | họp báo sau quyết định |
| `FOMC_MINUTES` | MEDIUM | biên bản: thông tin cũ 3 tuần, ít bất ngờ |
| `BEA_PIO` (thu nhập/chi tiêu cá nhân) | HIGH | chứa PCE — thước đo lạm phát Fed đặt mục tiêu |
| `BEA_GDP` ước tính `ADVANCE` | HIGH | số GDP đầu tiên của quý |
| `BEA_GDP` `SECOND` / `THIRD` | MEDIUM | thường chỉ sửa nhỏ |
| `DOL_JOBLESS_CLAIMS` | MEDIUM | số tuần, biến động nhiều |
| **Mọi sự kiện / biến thể khác** (vd. GDP `INITIAL`/`UPDATED`, GDP không rõ lần ước tính, CPI chưa có nguồn) | **HIGH** + ghi chú `IMPORTANCE_UNKNOWN_EVENT` | hướng an toàn: không biết thì coi là quan trọng |

**Phiên bản:** mức là **chính sách**, không ghi vào bản ghi của nguồn; bảng hợp nhất tính khi đọc và mang `policy_version`. Test giữ "dấu vân tay" (SHA-256) của toàn bộ bảng mức + cửa sổ theo phiên bản → đổi một con số mà quên đổi `POLICY_VERSION` thì test đỏ.

## 2. Cửa sổ rủi ro cơ bản

| Trường hợp | Cửa sổ `[start, end)` |
| --- | --- |
| Giờ đã xác nhận, HIGH | 15 phút trước → 15 phút sau |
| Giờ đã xác nhận, MEDIUM | 5 phút trước → 10 phút sau |
| Giờ đã xác nhận, LOW (chưa dùng) | 0 → 5 phút sau |
| Giờ **theo quy tắc** (DOL thứ Năm 8:30 ET — người dùng chọn ở 8f) | như giờ xác nhận, ghi chú `TIME_BY_RULE` (`time_confirmed` vẫn `false`) |
| Chưa chắc giờ (`all_day`, FOMC chưa có lịch tháng, tuần lễ DOL) | **cả ngày** 0:00–24:00 giờ New York (ngày đổi giờ dài 23 / 25 giờ) |
| Có cờ `CALENDAR_SOURCES_DISAGREE` / `UNUSUAL_RELEASE_TIME` dù có giờ | **cả ngày**, ghi chú `TIME_DISTRUSTED_WHOLE_DAY` |
| `REMOVED` (hủy / mất khỏi lịch) | không có cửa sổ; chỉ hiện khi `include_removed` |

**Lý do + giới hạn:** các con số phút là **giá trị khởi đầu, chưa hiệu chỉnh** trên dữ liệu giá thật (không gọi là "độ tin cậy"). 15 phút sau cho HIGH khớp đặc tả làn nhanh (FAST-03: chặn 10–15 phút); trước giờ công bố chặn để tránh vào lệnh ngay trước tin (spread giãn). Hiệu chỉnh khi có dữ liệu giá quanh các lần công bố (GĐ2 / GĐ6) → đổi phiên bản. **Gộp** các cửa sổ chồng nhau (2-C08) và áp vào Safety là việc của GĐ2; ở GĐ1 chỉ cung cấp danh sách + `active_windows(as_of)`.

## 3. Bảng hợp nhất

`economic_calendar(store, as_of, start, end)`: sự kiện của `fed_fomc`, `bea_schedule`, `dol_claims_schedule` **đã biết tại `as_of`** (point-in-time, revision mới nhất), có cửa sổ giao `[start, end)`. Mỗi mục: nguồn, khóa, revision, sự kiện, biến thể, giờ công bố UTC, ngày giờ New York, `time_confirmed`, `all_day`, trạng thái, cờ của nguồn, mức + lý do + phiên bản, cửa sổ, ghi chú.

**Không có forecast (1C-C07, DEC-01):** mọi mục `forecast = None`, `forecast_status = surprise_status = "INSUFFICIENT_DATA"`; không bao giờ suy "bất ngờ" từ số khác. Cửa sổ vẫn có đủ.

**Lỗi tìm được khi làm (ING-13):** `as_of(..., event_from, event_to)` ở cả store bộ nhớ lẫn SQL lọc theo `event_time` **trước** khi chọn revision mới nhất → sự kiện bị dời ra ngoài khoảng lọc vẫn trả về bản cũ như còn hiệu lực. Đã sửa: lọc sau khi chọn revision (test `test_event_filter_applies_after_latest_revision`). Các chỗ dùng trước đó (`values_due`, `release_for`, `scheduled_match`) chỉ bị ảnh hưởng theo hướng gọi thừa / gắn nhầm lần công bố cũ khi lịch bị dời — chưa từng xảy ra trên dữ liệu thật.
