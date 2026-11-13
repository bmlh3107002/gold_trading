# Thiết kế — BLS: lịch + số CPI, việc làm (NFP), PPI (GĐ1 bước 8e)

> Tạo 2026-11-13. Code: `backend/src/gold_trading/ingestion/sources/bls.py`, lệnh `cli bls`; test `backend/tests/test_bls.py` (+ bộ chạy, bảng lịch hợp nhất, replay). Ảnh hưởng quyết định giao dịch (cửa sổ chặn quanh CPI / NFP / PPI) → mọi thay đổi ghi ở đây kèm lý do.

## 1. Truy cập (kiểm từ máy người dùng 2026-11-13)

| Đường | Máy người dùng | Máy chủ đám mây |
| --- | --- | --- |
| `www.bls.gov` (trang lịch, điều khoản, file `.ics`) | 403 với chương trình, **trình duyệt xem được** | 403 |
| `api.bls.gov` (API v2) | 200 (khóa `GT_BLS_API_KEY` đăng ký 2026-11-13, nằm trong `.env`) | không kết nối được |

Không giả trình duyệt để lách (DEC-18 giữ điều này). Điều khoản: `bls` → `VERIFIED` theo DEC-18 (`11-dieu-khoan-nguon.md#bls`).

## 2. Lịch — bảng chép tay có phiên bản (`bls_schedule`)

- Người dùng mở 3 trang bằng trình duyệt (`/schedule/news_release/cpi.htm`, `empsit.htm`, `ppi.htm`), chép nguyên văn bảng "Schedule of Releases for …" (tháng số liệu, ngày, giờ 08:30 AM) → `bls._TABLE`, phiên bản `bls-schedule-2026.11.13`: 3 × 14 lần công bố, từ số tháng 10/2026 tới tháng 11/2027 (công bố tới 15/12/2027).
- Mọi lần công bố 08:30 giờ New York → UTC theo `zoneinfo` (13:30 mùa đông, 12:30 mùa hè). `time_confirmed = true`, `basis = OFFICIAL_TABLE_COPIED`.
- Kiểm bảng khi chạy: tháng số liệu liên tiếp, ngày tăng dần, ngày công bố sau khi hết tháng số liệu, chỉ thứ Hai–Sáu — sai → `PARSE_ERROR`.
- **Sắp hết bảng** (lần công bố cuối của một loại < 45 ngày nữa) → lần kiểm lịch `INVALID` `SCHEDULE_TABLE_EXPIRING` → nguồn "Hỏng" trên trang Nguồn dữ liệu → bảng lịch hợp nhất không tin giờ, **chặn cả ngày** (hướng an toàn). Việc cần làm lúc đó: người dùng chép bảng năm mới (bảng hiện tại đủ tới khoảng 31/10/2027).
- Không gọi mạng → lịch luôn ghi được trước số (thứ tự việc trong bộ chạy: lịch trước, số sau).
- Hạn chế: BLS dời lịch giữa chừng (chính phủ đóng cửa…) → bảng chép tay không tự biết. Phát hiện gián tiếp: giờ công bố qua 15 phút mà chưa có số → `UNKNOWN_LATE`, cửa sổ kéo dài (1C-C05); số tới ngoài lịch → cờ `UNSCHEDULED_CHANGE`; số mới nhất cũ hơn 45 ngày → nguồn số STALE.

## 3. Số — API v2 (`bls_values`)

- Một yêu cầu POST JSON cho cả 7 series (`startyear` năm trước, `endyear` năm nay theo giờ ET); khóa trong **thân** yêu cầu, không trong URL; không đi theo chuyển hướng; tối đa 5 MB.

| Series | Lần công bố | Ý nghĩa | Đơn vị (khoảng hợp lệ) |
| --- | --- | --- | --- |
| `CUSR0000SA0` | CPI | CPI-U toàn bộ, đã điều chỉnh mùa vụ | chỉ số 1982–84 (100–1000) |
| `CUSR0000SA0L1E` | CPI | CPI lõi | như trên |
| `CUUR0000SA0` | CPI | CPI-U chưa điều chỉnh mùa vụ | như trên |
| `CES0000000001` | EMPSIT | việc làm phi nông nghiệp (NFP), nghìn người | 100.000–250.000 |
| `LNS14000000` | EMPSIT | tỷ lệ thất nghiệp | 0–30 % |
| `CES0500000003` | EMPSIT | lương giờ trung bình khu vực tư | 10–100 USD |
| `WPSFD4` | PPI | PPI nhu cầu cuối cùng | chỉ số 2009–11 (50–500) |

- Phản hồi hỏng bất kỳ chỗ nào → **cả lần tải `INVALID`, không ghi gì**: không phải JSON, thiếu / thừa / trùng series, kỳ lạ, kỳ trùng, giá trị không phải số thập phân, ngoài khoảng (bắt lệch dấu thập phân / đổi đơn vị), số của tháng chưa kết thúc. `M13` (trung bình năm) bỏ qua; `-` → không có số (`VALUE_NOT_AVAILABLE`, không phải 0).
- API từ chối (`status` khác `REQUEST_SUCCEEDED`): khóa sai / hết hạn → `AUTH_FAILED` (MISSING ngay — ING-30); vượt hạn mức ngày → `RATE_LIMITED`; khác → `API_NOT_PROCESSED`. Không bao giờ chép thông điệp gốc.
- Mỗi (series, tháng) một dữ kiện; `event_time` = 0:00 ET ngày đầu tháng sau. Đổi số **hoặc** đổi chú thích (vd. bỏ `P` sơ bộ) → revision mới (ING-19). Cờ `PRELIMINARY` khi có chú thích `P`.
- Gắn lần công bố: số mới / đổi trong 3 ngày sau một lần công bố cùng loại trên lịch → `release_ref`, `available_at = max(giờ công bố, cuối kỳ)`, `latency_seconds` (ING-17). Không có → `INITIAL_LOAD` (lần nạp đầu) / `UNSCHEDULED_CHANGE`.
- Lịch gọi (`values_due`): trong 90 phút sau giờ công bố mà chưa có số gắn lần đó → gọi mỗi 60 giây (`RELEASE_WINDOW`; tối đa ~90 lần, hạn mức 500 / ngày); có số rồi → thôi. Ngoài ra đối chiếu khi lần OK cuối cũ hơn 7 ngày. Thiếu / sai khóa → không gọi BLS.
- TTL: tải `fetch_ttl` 8 ngày; `data_ttl` 45 ngày (số mới nhất bình thường cũ nhất ~44 ngày giữa hai lần PPI) → quá → STALE.

## 4. Bảng lịch hợp nhất + mức quan trọng (chính sách `event-policy-2026.11.13-bls`)

| Sự kiện | Mức | Cửa sổ | Lý do |
| --- | --- | --- | --- |
| `BLS_CPI` | HIGH | 15 phút trước → 15 phút sau | lạm phát tiêu dùng — tác động mạnh tới kỳ vọng lãi suất |
| `BLS_EMPSIT` (NFP) | HIGH | 15 / 15 | việc làm + thất nghiệp |
| `BLS_PPI` | MEDIUM | 5 / 10 | lạm phát phía sản xuất, thường ít bất ngờ hơn CPI |

Số actual ghép qua `release_ref` (`ACTUAL_SOURCES`); chưa có số sau giờ công bố → cửa sổ kéo dài như mọi nguồn (1C-C05). Con số cửa sổ là giá trị khởi đầu chưa hiệu chỉnh (như `17-…`).

## 5. Kiểm chứng (2026-11-13)

- `tests/test_bls.py` 42 test (bộ nhớ + SQLite): giờ UTC đọc tay ở cả giờ chuẩn / mùa hè và sát ngày đổi giờ 2027; kiểm bảng (4 kiểu sai); sắp hết bảng → INVALID + bảng hợp nhất chặn cả ngày; phản hồi thật đọc tay (CPI 337.476, NFP 159293 sơ bộ, PPI 160.254, chỗ ghép hai đoạn dán 158650); 10 kiểu phản hồi hỏng; 4 kiểu từ chối của API; lần nạp đầu + gắn lần công bố (PPI 13/11 trễ 30 phút); nạp lại không thêm; BLS sửa số + bỏ "sơ bộ" → revision, quá khứ giữ; giả lập NFP 4/12 (số tới sau 60 s → `RECEIVED`, cửa sổ 13:15–13:45 UTC, thôi gọi); API chậm cập nhật → `UNKNOWN_LATE` + kéo dài cửa sổ, gọi tiếp tới 90 phút; tháng chưa kết thúc → INVALID; thiếu khóa → không gọi; khóa chỉ trong thân POST; CLI.
- **Soát lại** (kịch bản riêng): đọc độc lập nguyên văn 3 bảng người dùng dán → khớp 42 / 42 dòng trong code; không ngày nào trùng lễ liên bang (bảng `federal_holidays` 2026–2027); 08:30 ET đúng ở mọi ngày; NFP 14 / 14 vào thứ Sáu; bộ chạy mô phỏng ngày NFP: gọi API 13:30, 13:31, 13:32, 13:33 (số có lúc 13:33) rồi dừng, cửa sổ chặn 13:15–13:44:30.
- **Phát hiện:** replay đảo thứ tự (số trước lịch) → số BLS không gắn lần công bố (`available_at` trống → biết từ lúc nạp, không sớm hơn) — chạy thật không xảy ra; ghi trong `test_replay.py`.
- **Kiểm trên máy người dùng 2026-11-13: đạt** (mục 21): lịch 41, số 154, trang + chân trang, bảng lịch hợp nhất. Giới hạn ghi nhận: lần nạp đầu gắn mọi số thay đổi của một loại vào lần công bố gần nhất trong 3 ngày (vd. 13 số PPI → `PPI:2026-10`) → số cũ bị coi là biết muộn hơn thực tế (an toàn, không nhìn trước).
- **Còn:** bắt thật NFP 4/12/2026 hoặc CPI 10/12/2026 20:30 giờ VN (Gate GĐ1).
