# Thiết kế — Census: lịch + số actual doanh số bán lẻ (GĐ1 bước 8d, ING-09 / ING-17 / ING-19)

> Tạo 2026-11-13. Điều khoản Census: `VERIFIED` (`11-dieu-khoan-nguon.md#census`) — **phải hiện nguyên văn** *"This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau."*: đã có ở chân mọi trang (`SourceAttribution.tsx`). Code: `backend/src/gold_trading/ingestion/sources/census.py`. Cùng khuôn với BEA (`13-bea.md`): khung `10-nguon-ngoai.md`, đồng bộ lịch `calendar_sync.py`.

## 1. Hai nguồn, chung nhà cung cấp `census`

| Nguồn | `kind` | Lấy từ | Khóa | TTL |
| --- | --- | --- | --- | --- |
| `census_schedule` | `calendar` | Lịch chỉ số kinh tế dạng danh sách `www.census.gov/economic-indicators/calendar-listview.html` (năm mới nhất) + `calendar-listview-<năm nay>.html` nếu khác, **đối chiếu** lịch riêng của khảo sát bán lẻ `www.census.gov/retail/release_schedule.html` | Không | `fetch_ttl` 26 giờ |
| `census_marts` | `macro` | API `api.census.gov/data/timeseries/eits/marts` (Advance Monthly Sales for Retail and Food Services) | `GT_CENSUS_API_KEY` (bắt buộc) | `fetch_ttl` 8 ngày, `data_ttl` 55 ngày |

## 2. Lịch (`census_schedule`)

- Chỉ lấy dòng **"Advance Monthly Sales for Retail and Food Services"**. Mỗi dòng có ngày + giờ dạng chữ (giờ miền Đông) **và** mã ẩn `AYYYYMMDDHHMM` + kỳ `AYYYYMM` → **hai cách ghi phải khớp**, lệch → INVALID cả lần tải. Năm trên trang phải đúng năm đã yêu cầu.
- `logical_key = RETAIL:<năm>-<tháng số liệu>` (vd. `RETAIL:2026-10`) → dời ngày = revision (1C-C03), bỏ khỏi cả hai trang = `REMOVED` (1C-C02).
- Đối chiếu lịch bán lẻ (bảng "Advance Monthly Retail Trade Report", tiêu đề cột phải là "Release Date at 8:30 am"; "To be announced" = chưa có ngày, bỏ qua): khác ngày, hoặc lịch chung ghi giờ khác 8:30 → cờ `CALENDAR_SOURCES_DISAGREE`, `all_day`, `event_time` = 00:00 ET (1C-C06). Kỳ chỉ có ở lịch bán lẻ → thêm sự kiện cả ngày + cờ. Kỳ cũ hơn bảng bán lẻ (bảng chỉ giữ từ vài tháng trước) không coi là lệch.
- Không còn lần công bố nào trong tương lai → INVALID.

## 3. Số actual (`census_marts`)

| `category_code` | Ý nghĩa | `data_type_code` |
| --- | --- | --- |
| `44X72` | Bán lẻ + ăn uống, tổng (con số tin chính) | `SM` mức (triệu USD), `MPCSM` % so tháng trước |
| `44Y72` | … trừ ô tô và phụ tùng | `SM`, `MPCSM` |
| `44W72` | … trừ ô tô và trạm xăng | `SM`, `MPCSM` |

Mã đọc từ công cụ Time Series chính thức của Census (`/econ/currentdata/dbsearch?programCode=MARTS`, nhãn "44X72: Retail Trade and Food Services", "ex Auto", "ex Auto and Gas"; "SM = Sales - Monthly", "MPCSM = Sales - Monthly Percent Change"), 2026-11-13. Chỉ lấy dòng `seasonally_adj = yes` và `error_data = no` (dòng `yes` là sai số chọn mẫu, không phải doanh số). Mỗi lần gọi: 2 yêu cầu (`time=<năm trước>`, `time=<năm nay>`); đầu năm chưa có số năm nay → HTTP 204 → rỗng, không phải lỗi.

**Kiểm chéo (an toàn):** % Census công bố (`MPCSM`) phải khớp % tự tính từ mức (`SM`) cùng lần tải, lệch tối đa **0,1 điểm** (Census tính từ số chưa làm tròn) — lệch hơn → INVALID cả lần tải (bắt mã sai, cột lệch, dữ liệu hỏng). Đã kiểm 126 số thật 2025–2026: khớp hết.

Bản ghi: `logical_key = <ngành>:<loại>:<kỳ>` (vd. `44X72:SM:2026-09`), `event_time` = 00:00 ET ngày đầu tháng sau. Payload: `value` (chuỗi đúng chữ số Census), `value_status`, `unit` (`USD_MILLIONS` / `PERCENT`), `seasonally_adjusted`, `release_ref`, `latency_seconds`, `flags`. "(S)", "(NA)", "(X)"… → `value = None`, `NOT_AVAILABLE` (1C-C01). Sửa số (Census sửa 2 tháng trước mỗi lần công bố + sửa năm) → revision mới (ING-19, 1C-C08), gắn lần công bố trong 3 ngày qua + độ trễ (ING-17); ngoài lịch → `UNSCHEDULED_CHANGE`.

**Khóa:** đi trong tham số `key` (bộ che log che theo giá trị + tên `key`). Census báo khóa **sai** bằng 302 sang `invalid_key.html` và **thiếu** bằng 302 sang `missing_key.html` (kiểm thật 13/11) → bộ tải **không đi theo chuyển hướng**: `AUTH_FAILED` / `KEY_MISSING` (lỗi "chết" → MISSING ngay). Chuyển hướng khác → `UNEXPECTED_REDIRECT`.

**Khi nào gọi** (`values_due`): 90 phút sau giờ công bố đã xác nhận, hoặc đối chiếu mỗi 7 ngày (như BEA).

**`data_ttl` 55 ngày:** số tháng mới nhất bình thường cũ nhất ~51 ngày tính từ cuối kỳ (vd. số tháng 3/2026 công bố 21/4, trước đó số mới nhất là tháng 2 hết kỳ 01/3).

## 4. Kiểm 2026-11-13

- Lịch tải trực tiếp: 14 lần công bố từ 17/11/2026 (số tháng 10, 13:30 UTC = 8:30 ET) tới 15/12/2027, 0 cờ lệch, trùng file test. Giờ mùa hè 12:30 UTC.
- API thật: khóa giả → `AUTH_FAILED` → MISSING; không khóa → `KEY_MISSING`; 108 dòng log JSON không lộ khóa.
- **Chưa thấy phản hồi số thật** (chưa có khóa): test dùng phản hồi dựng theo dạng chuẩn của Census Data API với số thật (tổng tháng 9/2026 745.021 triệu USD, +0,8%), khớp `marts_current.xlsx`. Kiểm thật khi người dùng có khóa.

## 5. Chưa làm

Chạy tự động + kiểm trên máy với khóa thật (8g / mục 12 file kế hoạch); hiển thị (DSH-09); mức quan trọng (ING-20); ngưỡng "sửa số lớn". Lệnh chạy tay: `docker compose exec backend python -m gold_trading.ingestion.cli census [--dry-run]`.
