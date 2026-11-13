# Thiết kế — DOL: trợ cấp thất nghiệp hằng tuần (GĐ1 bước 8f, ING-09 / ING-17 / ING-19)

> Tạo 2026-11-13. Điều khoản DOL: `VERIFIED` chỉ cho bản tin PDF (`11-dieu-khoan-nguon.md#dol`): public domain, ghi nguồn "U.S. Department of Labor" (đã có ở chân trang web), không ngụ ý bảo trợ. Code: `backend/src/gold_trading/ingestion/sources/dol.py`, `market/federal_holidays.py`. Máy người dùng tải được bản tin (200, 13/11) — kiểm trước khi code (bài học 8d).

## 1. Hai nguồn, chung nhà cung cấp `dol`

| Nguồn | `kind` | Lấy từ | TTL |
| --- | --- | --- | --- |
| `dol_claims_schedule` | `calendar` | **Sinh theo quy tắc** (không tải) | `fetch_ttl` 26 giờ (sinh mỗi ngày) |
| `dol_claims` | `macro` | Bản tin PDF chính thức `www.dol.gov/ui/data.pdf` (địa chỉ cố định, không khóa) | `fetch_ttl` 8 ngày, `data_ttl` 16 ngày |

## 2. Lịch theo quy tắc (người dùng chọn 2026-11-13)

DOL **không đăng lịch dạng đọc được** (trang tin tức trả 403 với chương trình; `oui.doleta.gov` chỉ có dữ liệu). Quy tắc DOL: công bố **thứ Năm 8:30 sáng giờ miền Đông**; tuần có ngày lễ thì đổi ngày.

- Tuần thường: sự kiện `CLAIMS:<thứ Năm>` lúc 8:30 ET, `basis = "RULE"`, **`time_confirmed = false`**, `all_day = false`.
- Tuần có ngày lễ liên bang (thứ Hai–Sáu): **không đoán ngày mới** — ba sự kiện cả ngày thứ Tư / thứ Năm / thứ Sáu (`CLAIMS:<thứ Năm>:WED`, `CLAIMS:<thứ Năm>`, `CLAIMS:<thứ Năm>:FRI`), cờ `HOLIDAY_WEEK`, ghi tên ngày lễ. Hướng an toàn: chặn rộng hơn (kể cả tuần có ngày lễ thứ Hai, nơi DOL thường không đổi ngày).
- Sinh 8 tuần tới (+ giữ 7 ngày trước). Đổi bảng ngày lễ → revision (`sync_calendar`).
- Nơi dùng lịch (GĐ sau) phải hiểu: `basis = RULE` + `time_confirmed = false` = giờ theo quy tắc, chưa xác nhận.

**Ngày lễ liên bang** (`market/federal_holidays.py`): tính theo 5 U.S.C. 6103 (cố định: 1/1, 19/6 từ 2021, 4/7, 11/11, 25/12; thứ Hai: MLK, Washington, Memorial (cuối tháng 5), Labor, Columbus; Lễ Tạ ơn thứ Năm thứ tư tháng 11; Nhậm chức 20/01 năm sau bầu cử); thứ Bảy → nghỉ bù thứ Sáu, Chủ nhật → thứ Hai. Khác bảng ngày lễ thị trường: có Columbus + Veterans Day, không Good Friday. **Chưa đối chiếu trang OPM** (OPM chặn máy chủ đám mây) — đã đối chiếu chéo với bảng ngày lễ thị trường 2024–2027 (test). **Không biết** ngày nghỉ đột xuất theo sắc lệnh → bắt bằng đối chiếu sau công bố (mục 3).

## 3. Số liệu từ bản tin PDF

Đọc chữ 2 trang đầu bằng `pypdf` (thuần Python, BSD). Lấy:

| `logical_key` | Câu trong bản tin |
| --- | --- |
| `ICSA:<thứ Bảy cuối tuần>` | "In the week ending …, the advance figure for seasonally adjusted initial claims was N, an increase/a decrease of X / unchanged from the previous week's revised level. The previous week's level was revised up/down by A from B to C." (tuần này + tuần trước đã sửa) |
| `IC4WSA:<…>` | "The 4-week moving average was …" (cùng mẫu) |
| `CCSA:<…>` | "The advance number for seasonally adjusted insured unemployment during the week ending … was …" (tuần trước đó một tuần) |

**Quyết định an toàn:**
- **Kiểm số học** cho cả ba câu: B ± A = C và C ± X = N; lệch → INVALID cả lần tải (bắt đọc nhầm chữ PDF / đổi mẫu câu).
- Giờ phát hành lấy từ dòng "EMBARGOED UNTIL 8:30 A.M. (Eastern) Thursday, November 12, 2026" — thứ phải khớp ngày; giờ ở tương lai so với lúc tải → INVALID. `available_at` = giờ này → point-in-time: trước 8:30 không ai thấy số.
- Tuần kết thúc phải là **thứ Bảy**, trước ngày phát hành ≤ 20 ngày (suy năm từ ngày phát hành); đơn tiếp tục phải trước đơn lần đầu đúng một tuần.
- Giờ phát hành không khớp lịch theo quy tắc → cờ `RELEASE_OFF_SCHEDULE` (DOL đổi lịch đột xuất / bảng ngày lễ sai) — cảnh báo, không chặn số.
- Tải lại bản tin cũ (giờ phát hành không mới hơn số đã có) → không ghi đè số đã sửa. Giá trị đổi → revision mới (ING-19); `latency_seconds` = lúc nhận − giờ phát hành (ING-17).
- Chỉ nhận PDF (`%PDF`), chỉ `www.dol.gov`, tối đa 10 MB.

**Khi nào tải** (`values_due`): 90 phút sau 8:30 ET thứ Năm tuần thường; tuần lễ: thứ Tư–Sáu 08:00–18:00 ET; ngoài ra đối chiếu mỗi 7 ngày.

## 4. Kiểm 2026-11-13

Bản tin thật 12/11/2026 (tuần Veterans Day 11/11 thứ Tư): đọc đúng 6 số (đơn lần đầu 200.000, tuần trước sửa 191.000; trung bình 4 tuần 195.250; đơn tiếp tục 1.697.000, tuần trước 1.717.000), kiểm số học khớp, giờ phát hành thứ Năm 8:30 nằm trong vùng chặn cả ngày của tuần lễ → không cờ; nguồn HEALTHY; tải lại không thêm gì.

## 5. Chưa làm / giới hạn

Mẫu câu mới chỉ kiểm trên **một** bản tin (chưa lấy được bản cũ — trang lưu trữ chặn chương trình) → mẫu lạ sẽ ra INVALID (hướng an toàn) và phải sửa. Chạy tự động (8g), hiển thị (DSH-09), đối chiếu bảng ngày lễ với OPM (người dùng chụp trang OPM). Lệnh chạy tay: `docker compose exec backend python -m gold_trading.ingestion.cli dol [--dry-run]`.
