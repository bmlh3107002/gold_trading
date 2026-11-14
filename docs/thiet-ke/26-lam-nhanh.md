# Thiết kế — Làn nhanh (GĐ2 bước 4 — FAST-01..03; 2-C07..C09)

> Tạo 2026-11-14. Ngưỡng: **DEC-20** (người dùng chốt, `docs/giai-doan/GD2-event-orchestrator.md`). Code: `backend/src/gold_trading/risk/blocks.py`, `storage/risk_blocks.py` (4a); `risk/fast_lane.py` (4b); 4c–4d sau.

## 1. Quyết định (DEC-20)

| # | Nội dung |
| --- | --- |
| 1 | Số liệu HIGH (CPI, NFP, FOMC, PCE…) → chặn mở lệnh mới **15 phút** kể từ lúc hệ thống nhận số (thêm vào cửa sổ lịch ±15 phút đã có) |
| 2 | Spread > **3 ×** trung vị 60 phút cùng nguồn, kéo dài ≥ 5 giây → chặn; < 1,5 × liên tục 2 phút → gỡ |
| 3 | Chỉ thông cáo chính sách tiền tệ Fed **không có trên lịch** → chặn 15 phút; phát biểu Fed, tin Bộ Tài chính chỉ gắn cờ. RSS tải 15 phút / lần → tin bất ngờ có thể biết trễ tới 15 phút |
| 4 | Ngân sách độ trễ **10 giây** (từ lúc biết tới lúc ghi lệnh cấm); vòng làn nhanh 2 giây; vượt → cảnh báo + mặc định chặn (2-C09) |
| 5 | Lệnh cấm **có hạn, tự hết hạn**, **không gạt công tắc Safety**; mở lệnh mới chỉ khi công tắc ACTIVE **và** không còn lệnh cấm; hành động bảo vệ không bị chặn; web hiện băng cảnh báo |

## 2. Lệnh cấm (4a — 2026-11-14)

- Bảng chỉ-thêm `risk_blocks` (migration 0016): `block_id = sha256(loại | phạm vi | nguyên nhân)[:40]` → cùng nguyên nhân ghi lại không sinh lệnh cấm mới (idempotent, replay). Cột: `kind` (`RELEASE` / `NEWS` / `SPREAD` / `LATENCY`), `scope` (`*` = mọi nguồn, hoặc `feed_id` cho spread), `reason_code` (mã ngắn), `start_at`, `end_at` (`NULL` = tới khi gỡ — spread), `cause_ref`, `created_at`, `policy_version`, `latency_ms`.
- Bảng chỉ-thêm `risk_block_lifts`: gỡ lệnh cấm không có giờ hết (mỗi lệnh cấm gỡ một lần).
- **Có hiệu lực tại t** khi `created_at <= t` (point-in-time: chỉ từ lúc hệ thống biết), `start_at <= t`, `t < end_at` (nếu có), chưa gỡ tới `t`.
- **Safety:** `AccountRegistry.allows_new_orders` = đọc được DB + công tắc ACTIVE + chủ tài khoản không bị khóa + **không có lệnh cấm còn hiệu lực** cho nguồn giá của tài khoản (`*` hoặc đúng `feed_id`). Đọc lệnh cấm lỗi → **chặn**. Công tắc Safety không đổi. API `GET /api/accounts/{id}/status` thêm `entry_blocks` (loại, mã lý do, phạm vi, bắt đầu, hết hạn, nguyên nhân).
- Ghi chú: `RiskEngine` (GĐ5) hiện đọc `SafetySupervisor` trực tiếp — khi nối lệnh thật phải đọc qua `AccountRegistry.allows_new_orders` (có lệnh cấm).
- **Kiểm chứng:** `tests/test_risk_blocks.py` 16 test (bộ nhớ + SQLite + API): idempotent, point-in-time (biết lúc 13:31 thì 13:30:30 chưa chặn), đúng biên `end_at`, phạm vi nguồn, spread mở tới khi gỡ, gỡ một lần, quá khứ không bị viết lại, dữ liệu sai; API: công tắc ACTIVE + lệnh cấm → không mở lệnh, `safety_state` vẫn ACTIVE; lệnh cấm hết hạn → mở lại; spread nguồn khác không áp; đọc lỗi → chặn. Postgres 16: migration lên / xuống, `alembic check` không lệch.

## 3. Số liệu HIGH + thông cáo Fed (4b — 2026-11-14)

Code: `backend/src/gold_trading/risk/fast_lane.py` (`POLICY_VERSION = fast-lane-2026.11.14`). Chỉ luật, không LLM (FAST-02). Đổi con số / luật → đổi phiên bản + ghi ở đây.

**Safety chặn mở lệnh mới khi có ít nhất một trong hai:**

1. **Lệnh cấm đã lưu** (bảng `risk_blocks`, mục 2) — do bộ xử lý job `FAST_LANE` của orchestrator ghi.
2. **Cửa sổ lịch kinh tế, tính khi đọc** (`CalendarBlocks`): bảng lịch hợp nhất GĐ1 (`economic_calendar`) tại thời điểm xét, **có trạng thái nguồn** (`health_map`), bộ nhớ đệm 5 giây cho mọi tài khoản. Mỗi sự kiện có cửa sổ → `CALENDAR_<mức>` trong `[window_start, window_end)` (đã gồm kéo dài khi chưa có số, cả ngày khi không tin giờ — chính sách GĐ1, `docs/thiet-ke/17-…`). Sự kiện HIGH đã nhận số → thêm `RELEASE_HIGH_RECEIVED` từ lúc biết số, 15 phút thị trường mở. Lý do tính khi đọc mà không lưu: lịch đổi (dời giờ, nguồn hồi phục) thì cửa sổ đổi theo đúng chính sách; vẫn point-in-time (chỉ dữ liệu `known_at <= lúc xét`), tính lại được để kiểm tra.

Đọc một trong hai lỗi → **chặn**. Cùng nguyên nhân ở cả hai (số HIGH đã nhận) → cùng `block_id` → chỉ tính một lần (`dedupe`).

**Luật cho từng sự kiện (job `FAST_LANE`, phiên bản bộ xử lý `fast-lane-1`):**

| Sự kiện | Kết quả |
| --- | --- |
| Số liệu khớp lần công bố **HIGH** trên lịch (CPI, NFP, PCE…) | `RELEASE` / `RELEASE_HIGH_RECEIVED`: từ lúc hệ thống nhận số đầu tiên của lần công bố, 15 phút thị trường mở; nhiều chuỗi số cùng lần công bố → một lệnh cấm |
| Số liệu khớp lần công bố mức thấp hơn (PPI, GDP lần 2, trợ cấp thất nghiệp) | chỉ cờ `RELEASE_MEDIUM` (cửa sổ lịch của nó vẫn áp) |
| Số liệu **không khớp** lần công bố nào (không `release_ref`, hoặc lần công bố không có trên lịch) | coi là HIGH (an toàn): `RELEASE_UNMATCHED` 15 phút từ lúc biết; nhiều số cùng nguồn cùng phút → một lệnh cấm |
| Thông cáo `fed_rss_monetary` trùng ngày + cách giờ ≤ 60 phút một sự kiện FOMC **HIGH** trên lịch | `RELEASE` / `FOMC_RECEIVED`: 15 phút từ lúc thấy tin |
| Như trên nhưng sự kiện trên lịch mức thấp hơn (biên bản họp) | chỉ cờ `FED_POLICY_SCHEDULED_MEDIUM` |
| Thông cáo `fed_rss_monetary` **không có trên lịch** | `NEWS` / `FED_UNSCHEDULED_POLICY`: 15 phút từ lúc thấy tin (DEC-20 câu 3) |
| Thông cáo đăng quá 36 giờ trước lúc thấy (lần tải đầu, nguồn hỏng lâu) | chỉ cờ `FED_POLICY_OLD_ITEM` (không phải tin vừa ra). 36 giờ: giờ đăng chỉ có ngày vẫn được coi là mới |
| Bài sửa (revision > 0) | chỉ cờ `NEWS_REVISION` (đã xét ở bản đầu) |
| Phát biểu Fed, tin Bộ Tài chính, tin khác | chỉ cờ `NEWS_<nguồn>` (DEC-20 câu 3) |
| Không áp được luật (đọc lịch lỗi…) | ghi ngay `FAST_LANE_ERROR` 15 phút (số liệu / thông cáo tiền tệ) rồi báo lỗi → job thử lại / dead-letter |

Cờ (chỉ cảnh báo) nằm ở kết quả job (`output_ref = flag:<mã>`); tầng dùng `riskFlags` (GĐ3 News, GĐ4 Fusion) đọc sau. Lịch trong luật đọc tại `known_at` của sự kiện → replay ra cùng kết quả; `created_at` của lệnh cấm = lúc ghi thật (chỉ có hiệu lực từ lúc hệ thống biết), `latency_ms` = lúc ghi − lúc biết (Gate GĐ2 đo ở đây; ngân sách + vòng 2 giây ở 4d).

**Thị trường đóng (2-C07):** 15 phút chỉ đếm **phút thị trường mở** (lịch thị trường của hệ thống, gồm ngày lễ / giờ broker): tin lúc đóng cửa vẫn xử lý ngay, lệnh cấm kéo tới hết 15 phút đầu sau khi mở cửa (vd. thông cáo thứ Bảy → tới 18:15 giờ New York Chủ nhật); tin lúc 16:55 → 5 phút trước giờ nghỉ + 10 phút sau khi mở lại. Không tìm thấy giờ mở trong 8 ngày → chặn hết 8 ngày (an toàn).

**Gộp cửa sổ (2-C08):** `merge_windows` gộp các lệnh cấm chồng hoặc nối nhau thành một cửa sổ liền; API `GET /api/accounts/{id}/status` thêm `entry_block_windows` (bắt đầu, hết, các mã lý do). Ví dụ: CPI + trợ cấp thất nghiệp cùng 8:30 → một cửa sổ 8:15 tới 15 phút sau khi nhận số CPI; tuyên bố FOMC 14:00 + họp báo 14:30 → một cửa sổ 13:45–14:45.

**Giới hạn đã biết:**
- Tuần lễ (vd. Lễ Tạ ơn 25–27/11/2026): lịch trợ cấp thất nghiệp chưa chắc ngày → **chặn cả ngày** thứ Tư (có thể tới thứ Sáu) cho tới khi có số — chính sách GĐ1 bước 8f, nay áp thật vào Safety.
- RSS tải 15 phút / lần → thông cáo Fed có thể biết trễ tới 15 phút (đã nói với người dùng ở DEC-20).
- "Bất ngờ so dự báo" vẫn **không đủ dữ liệu** (DEC-01, không có forecast).
- Các con số (15 phút, 60 phút, 36 giờ) là giá trị khởi đầu, chưa hiệu chỉnh trên dữ liệu giá thật.

**Kiểm chứng:** `tests/test_fast_lane.py` 46 test (bộ nhớ + SQLite + API). Kịch bản soát lại riêng: 400 bộ lệnh cấm ngẫu nhiên so gộp cửa sổ với lấy mẫu từng phút; 307 mốc "15 phút thị trường mở" đếm lại bằng lấy mẫu 15 giây (gồm ngày đổi giờ 8/3 và 1/11, Giáng sinh, Lễ Tạ ơn, năm mới); chạy trọn quét → điều phối → Safety mỗi 10 giây từ 1 giờ trước FOMC 9/12 tới 1 giờ sau CPI 10/12: chặn đúng từng mốc, tin cũ không chặn.
