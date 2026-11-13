# Thiết kế — Bảng lịch kinh tế hợp nhất + mức quan trọng có phiên bản (GĐ1 bước 8g-2)

> Code: `backend/src/gold_trading/ingestion/event_importance.py` (chính sách), `ingestion/economic_calendar.py` (bảng hợp nhất), lệnh `python -m gold_trading.ingestion.cli lich --days 14`. Test: `backend/tests/test_economic_calendar.py`. Ảnh hưởng quyết định giao dịch (cửa sổ rủi ro sẽ được Safety / làn nhanh dùng ở GĐ2) → mọi thay đổi ghi ở đây kèm lý do.

## 1. Mức quan trọng (ING-20) — phiên bản `event-policy-2026.11.13-bls`

> 2026-11-13 (bước 8e): thêm `BLS_CPI`, `BLS_EMPSIT` (HIGH), `BLS_PPI` (MEDIUM) — chi tiết + lý do ở `24-bls.md` mục 4. Bản trước: `event-policy-2026.11.13`.

| Sự kiện | Mức | Lý do |
| --- | --- | --- |
| `FOMC_STATEMENT` | HIGH | quyết định lãi suất của Fed |
| `FOMC_PRESS_CONFERENCE` | HIGH | họp báo sau quyết định |
| `FOMC_MINUTES` | MEDIUM | biên bản: thông tin cũ 3 tuần, ít bất ngờ |
| `BEA_PIO` (thu nhập/chi tiêu cá nhân) | HIGH | chứa PCE — thước đo lạm phát Fed đặt mục tiêu |
| `BEA_GDP` ước tính `ADVANCE` | HIGH | số GDP đầu tiên của quý |
| `BEA_GDP` `SECOND` / `THIRD` | MEDIUM | thường chỉ sửa nhỏ |
| `DOL_JOBLESS_CLAIMS` | MEDIUM | số tuần, biến động nhiều |
| `BLS_CPI` / `BLS_EMPSIT` (NFP) | HIGH | lạm phát tiêu dùng / việc làm — tác động mạnh nhất tới vàng |
| `BLS_PPI` | MEDIUM | lạm phát phía sản xuất, ít bất ngờ hơn CPI |
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

## 4. Số actual + nguồn chết lúc công bố (1C-C05, 8g-3, 2026-11-13)

Sự kiện có số (`BEA_GDP`, `BEA_PIO` → `bea_nipa`; `DOL_JOBLESS_CLAIMS` → `dol_claims`) mang `actual_status`; FOMC = `NOT_APPLICABLE`. Ghép số với lần công bố: BEA theo `release_ref` (= khóa sự kiện lịch); DOL theo tuần kết thúc + series `ICSA` (các số khác trong bản tin là sửa tuần trước).

| Trạng thái | Khi nào | Cửa sổ |
| --- | --- | --- |
| `NOT_DUE` | chưa tới giờ công bố (cả ngày: chưa tới 0:00 New York) | như mục 2 |
| `AWAITING` | đã tới giờ, chưa có số, nguồn số khỏe, chưa quá 15 phút | kéo dài: luôn còn ≥ **5 phút** sau `as_of` |
| `UNKNOWN_SOURCE_DOWN` | đã tới giờ, chưa có số, nguồn số **không khỏe** (ING-30) | kéo dài như trên + ghi chú `ACTUAL_UNKNOWN` |
| `UNKNOWN_LATE` | quá **15 phút** chưa có số dù nguồn khỏe | kéo dài như trên + `ACTUAL_UNKNOWN` |
| `RECEIVED` | đã biết số (point-in-time theo `known_at`) | biết số sau cửa sổ gốc → cửa sổ tới lúc biết số (`ACTUAL_LATE`) |

**Trần kéo dài:** hết ngày New York của lần công bố (`ACTUAL_MISSING_END_OF_DAY`). Lý do: số không về cả ngày là chuyện **nguồn hỏng**, xử lý bằng trạng thái nguồn (STALE/MISSING → Safety GĐ2) chứ không bằng cửa sổ tin kéo dài vô hạn; trong ngày công bố thì mặc định an toàn là chặn. Chưa có số → không bao giờ "hết chặn" sớm.

**Tuần lễ DOL** (3 sự kiện cả ngày thứ Tư–Sáu): số của tuần đã **phát hành** (`available_at`) trước ngày đó → ngày đó không còn công bố: biết trước khi ngày bắt đầu → bỏ cửa sổ, biết giữa ngày → chặn tới lúc biết (`RELEASED_EARLIER_IN_WEEK`).

**Nguồn lịch không khỏe:** sự kiện **chưa tới** của nguồn đó → không tin giờ → cả ngày (`SCHEDULE_SOURCE_UNHEALTHY`).

**Trạng thái nguồn** truyền vào qua `health=health_map(check_log, store, as_of)`. Không truyền → chỉ xét số đến trễ. Người gọi để chặn giao dịch (Safety, GĐ2) **phải** truyền.

**Lỗi tìm được khi soát:** số DOL tuần lễ hệ thống biết muộn (nạp sau 1 ngày) làm cửa sổ "cả ngày thứ Tư" kéo sang tận thứ Sáu → sửa: không kéo quá hết ngày New York; thứ Năm/Sáu dựa vào giờ **phát hành** để biết không còn công bố.

## 5. Sửa số kỳ trước (ING-19, 1C-C08) — phiên bản `revision-policy-2026.11.13`

Bộ nạp BEA/DOL đã lưu mỗi lần sửa số thành revision mới (không viết lại quá khứ). `ingestion/revisions.py` chỉ **đọc**: tại `as_of`, so mỗi revision với revision ngay trước, gắn cờ khi `|lệch| ≥ ngưỡng`:

| Series | Ngưỡng "sửa lớn" | Lý do (giá trị khởi đầu, chưa hiệu chỉnh) |
| --- | --- | --- |
| `A191RL` GDP thực % năm hóa | 1,0 điểm % | sửa giữa các lần ước tính thường dưới 0,5 điểm |
| `DPCERGM`, `DPCCRGM` PCE % tháng | 0,2 điểm % | số làm tròn 0,1; sửa 0,2 đổi hẳn nhận định lạm phát tháng |
| `ICSA` đơn lần đầu | 10.000 | sửa tuần trước thường vài nghìn |
| `IC4WSA` trung bình 4 tuần | 5.000 | trung bình nên sửa nhỏ hơn |
| `CCSA` đơn tiếp tục | 30.000 | mức lớn hơn nhiều (~1,9 triệu) |
| Mức chỉ số PCE (`DPCERG`, `DPCCRG`) và series khác | không có → `NO_THRESHOLD` | không đoán ngưỡng; mức chỉ số đổi theo năm gốc |

Không có số / không phải số → `NOT_COMPARABLE` (không coi trống là 0, 1C-C01). Cờ **chỉ cảnh báo**, GĐ1 không dùng để chặn/cho phép giao dịch. Lệnh `cli lich` in các lần sửa 60 ngày qua.
