# Thiết kế — BEA: lịch công bố + số actual GDP, PCE (GĐ1 bước 8c, ING-09 / ING-17 / ING-19)

> Tạo 2026-11-13. Điều khoản BEA: `VERIFIED` (thỏa thuận API đọc nguyên văn, `11-dieu-khoan-nguon.md#bea`) — **phải hiện nguyên văn** câu *"This product uses the Bureau of Economic Analysis (BEA) Data API but is not endorsed or certified by BEA."* trên web: đã có ở chân mọi trang (`frontend/src/components/layout/SourceAttribution.tsx`, cùng câu ghi nguồn Fed). Code: `backend/src/gold_trading/ingestion/sources/bea.py`. Dùng chung khung `10-nguon-ngoai.md` + đồng bộ lịch `calendar_sync.py` (`12-lich-fomc.md` mục 3).

## 1. Hai nguồn, chung nhà cung cấp `bea`

| Nguồn | `kind` | Lấy từ | Khóa | TTL |
| --- | --- | --- | --- | --- |
| `bea_schedule` | `calendar` | File lịch ICS chính thức `www.bea.gov/news/schedule/ics/online-calendar-subscription.ics` (tên từng lần công bố + giờ UTC), **đối chiếu** file JSON máy đọc được mà trang lịch BEA dẫn tới (`apps.bea.gov/API/signup/release_dates.json`, mục "Machine-Readable Format") | Không | `fetch_ttl` 26 giờ (tải mỗi ngày) |
| `bea_nipa` | `macro` | API NIPA `apps.bea.gov/api/data` (GetData) | `GT_BEA_API_KEY` (UserID 36 ký tự, đăng ký miễn phí) | `fetch_ttl` 8 ngày, `data_ttl` 62 ngày |

**Lý do chọn ICS + JSON:** trang lịch HTML chỉ có tiêu đề + giờ dạng chữ; ICS có giờ UTC chuẩn và tiêu đề đủ để biết kỳ + lần ước tính; JSON chỉ có giờ theo nhóm. Hai file đều do BEA phát hành → lệch nhau = dấu hiệu một file chưa cập nhật → hướng an toàn.

## 2. Lịch (`bea_schedule`)

Chỉ lấy hai loại công bố: **GDP** (tiêu đề bắt đầu `GDP (` / `Gross Domestic Product,`) và **Personal Income and Outlays** (có PCE + chỉ số giá PCE). Bỏ qua: GDP theo bang/quận/Puerto Rico, thương mại, v.v.

| `logical_key` | Ví dụ tiêu đề BEA |
| --- | --- |
| `GDP:<năm>Q<quý>:<ước tính>` | "GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026" → `GDP:2026Q3:SECOND` |
| `PIO:<năm>-<tháng>` | "Personal Income and Outlays, October 2026" → `PIO:2026-10` |
| `PIO:<tháng đầu>..<tháng cuối>` | "Personal Income and Outlays, October and November 2025" (gộp sau chính phủ đóng cửa) |

Khóa theo **kỳ + lần ước tính** (không theo ngày) → BEA dời ngày = revision mới của cùng khóa (1C-C03); hủy / gộp kỳ → khóa cũ thành `REMOVED` (1C-C02). Ước tính nhận: Advance / Second / Third / Initial / Updated (hai tên sau dùng trong đợt đóng cửa 2025).

Payload: `event` (`BEA_GDP` / `BEA_PIO`), `title`, `period`, `estimate`, `includes`, `time_confirmed`, `all_day`, `release_local` (giờ ET), `release_date_local`, `tz`, `status`, `flags`. Chỉ giữ sự kiện từ 7 ngày trước trở đi.

**Quyết định an toàn:**
- Giờ ICS **không có** trong JSON (cùng nhóm) → cờ `CALENDAR_SOURCES_DISAGREE`, `time_confirmed = false`, `all_day = true`, `event_time` = 00:00 ET của ngày đó (chặn cả ngày) (1C-C06).
- Giờ JSON không khớp sự kiện ICS nào (và ngày đó không có sự kiện ICS cùng loại) → vẫn ghi sự kiện `GDP:UNMATCHED:<ngày>` / `PIO:UNMATCHED:<ngày>`, cả ngày + cờ (thêm sự kiện = hướng chặn nhiều hơn).
- ICS ghi ngày không giờ (`VALUE=DATE`) → cả ngày, chưa xác nhận giờ. Giờ "trôi" (không `Z`, không `TZID=America/New_York`) → **không đoán**, cả lần tải INVALID.
- Giờ ET ngoài 07:00–18:00 → cờ `UNUSUAL_RELEASE_TIME` (BEA thường 8:30 hoặc 10:00).
- Tiêu đề **giống** GDP / PIO mà không đọc được kỳ (vd. "Q3 2026", ước tính lạ) → INVALID cả lần tải. Tiêu đề cũ trước cửa sổ 7 ngày không đọc (định dạng cũ không làm hỏng).
- Không còn lần công bố GDP hoặc PIO nào trong tương lai → INVALID. `STATUS:CANCELLED` → coi như không có (→ `REMOVED`). > 2 sự kiện biến mất một lần → `TOO_MANY_REMOVALS`, không ghi (chung `sync_calendar`).

## 3. Số actual (`bea_nipa`)

| Series (BEA) | Bảng : dòng | Tần suất | Ý nghĩa |
| --- | --- | --- | --- |
| `A191RL` | T10101 : 1 | Quý | GDP thực, % so quý trước, năm hóa, đã điều chỉnh mùa vụ |
| `DPCERGM` | T20807 : 1 | Tháng | Chỉ số giá PCE, % so tháng trước |
| `DPCCRGM` | T20807 : 25 | Tháng | Chỉ số giá PCE lõi (trừ thực phẩm, năng lượng), % so tháng trước |
| `DPCERG` | T20804 : 1 | Tháng | Chỉ số giá PCE (mức) |
| `DPCCRG` | T20804 : 25 | Tháng | Chỉ số giá PCE lõi (mức) |

Mã series + dòng lấy từ `SeriesRegister.txt` chính thức của BEA (2026-11-13). Mỗi lần gọi: 3 yêu cầu (một mỗi bảng, năm nay + năm trước theo giờ ET) — xa dưới giới hạn 100 yêu cầu/phút. **% so cùng kỳ năm trước không lưu** (là phép tính của hệ thống từ mức chỉ số; làm khi cần, ghi rõ là số tự tính).

**Bản ghi:** `logical_key = <series>:<kỳ>` (`A191RL:2026Q3`, `DPCERGM:2026-09`), `event_time` = đầu kỳ kế tiếp lúc 00:00 ET (đổi sang UTC). Payload: `value` (**chuỗi số thập phân đúng chữ số BEA công bố**, không qua float), `value_status`, `unit`, `unit_mult`, `metric`, `release_ref`, `latency_seconds`, `flags`. `raw` = đúng một dòng số liệu của BEA.

**Quyết định an toàn:**
- **Phản hồi API của BEA chép lại khóa** (`Request.RequestParam` có `USERID`, đã kiểm với API thật bằng khóa giả) → **không bao giờ lưu nguyên phản hồi**; chỉ lưu từng dòng số liệu. Khóa đi qua `params` của httpx (bộ che log che theo giá trị + tên `UserID`).
- BEA báo khóa sai bằng **HTTP 200** + `APIErrorCode` `1` (kiểm thật 2026-11-13) → `AUTH_FAILED` (lỗi "chết" → nguồn MISSING ngay). Mã `7` / HTTP 429 → `RATE_LIMITED`. Mã khác → `BEA_API_ERROR_<số>`. Không đọc mô tả lỗi.
- "(NA)", "---", "(D)"... → `value = None`, `value_status = NOT_AVAILABLE`, cờ `VALUE_NOT_AVAILABLE` — **không bao giờ thành 0** (1C-C01). Số lạ (`1e5`, `NaN`, `1.2.3`, dấu phẩy sai chỗ) → INVALID cả lần tải.
- Series không còn ở dòng đã biết (bảng bị sắp xếp lại), thiếu series, cùng kỳ hai giá trị khác nhau, kỳ lạ → INVALID cả lần tải, không ghi gì.
- Thiếu / sai định dạng khóa → `KEY_MISSING` / `KEY_INVALID`, **không gọi BEA**.

**Revision (ING-19, 1C-C08):** cùng khóa mà giá trị đổi (ước tính lần 2, 3, cập nhật năm) → revision mới; xem lại quá khứ vẫn thấy số cũ. Giá trị không đổi → bỏ qua (nạp lại → cùng kết quả). Cờ "sửa lớn" chưa đặt ngưỡng (để ING-20 / GĐ sau, cần chọn ngưỡng có lý do).

**Đo độ trễ (ING-17):** khi ghi revision, nếu lịch BEA (đã biết tại lúc đó) có lần công bố cùng loại đã tới giờ trong 3 ngày qua → `release_ref` = khóa lần công bố, `available_at` = giờ công bố, `latency_seconds` = lúc nhận − giờ công bố. Không có → cờ `UNSCHEDULED_CHANGE` (BEA đổi số ngoài lịch); lần nạp đầu → `INITIAL_LOAD`.

**Khi nào gọi API** (`values_due`, BEA không khuyến khích gọi tự động khi chưa có số mới): trong **90 phút** sau giờ công bố GDP/PIO đã xác nhận → `RELEASE_WINDOW`; chưa có lần OK nào hoặc lần OK cuối > 7 ngày → `RECONCILE` (bắt sửa số ngoài lịch); còn lại không gọi. Nhịp gọi trong cửa sổ (mỗi phút) đặt ở 8g khi nối vào backend.

**TTL:** `data_ttl` 62 ngày — số PCE tháng mới nhất bình thường cũ nhất ~55 ngày tính từ cuối kỳ (số tháng 10 công bố 25/11, số tháng 11 công bố 23/12); quá 62 ngày nghĩa là BEA trễ lịch (vd. chính phủ đóng cửa) → STALE. `fetch_ttl` 8 ngày khớp nhịp đối chiếu 7 ngày.

## 4. Kiểm 2026-11-13

- Lịch tải trực tiếp: 28 lần công bố GDP/PIO từ 25/11/2026 tới hết 2027, **0 cờ lệch** giữa ICS và JSON; kế tiếp: GDP quý 3 lần 2 + PIO tháng 10 lúc 25/11/2026 13:30 UTC (8:30 ET). Giờ mùa hè 12:30 UTC, mùa đông 13:30 UTC — đều 8:30 ET.
- API thật với khóa giả: HTTP 200, mã `1`, phản hồi chép lại khóa → `AUTH_FAILED`, nguồn MISSING; 76 dòng log (có cả URL) không dòng nào lộ khóa.
- **Chưa kiểm được** phản hồi GetData thật (chưa có khóa): test dùng phản hồi **dựng** theo hướng dẫn API (bản 20/04/2026) với số thật từ file NipaData công khai. Kiểm thật khi người dùng có khóa (lệnh dưới).

## 5. Chưa làm

Chạy tự động trong backend + kiểm trên máy người dùng với khóa thật (8g); hiển thị lịch / số trên web (DSH-09); mức quan trọng (ING-20); ngưỡng cờ "sửa số lớn"; dùng lịch để chặn giao dịch (GĐ sau). Lệnh chạy tay: `docker compose exec backend python -m gold_trading.ingestion.cli bea` (`--dry-run`: không ghi DB; không có khóa thì vẫn tải lịch, phần số báo `KEY_MISSING`).
