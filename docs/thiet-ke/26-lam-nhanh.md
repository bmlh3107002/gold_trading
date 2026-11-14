# Thiết kế — Làn nhanh (GĐ2 bước 4 — FAST-01..03; 2-C07..C09)

> Tạo 2026-11-14. Ngưỡng: **DEC-20** (người dùng chốt, `docs/giai-doan/GD2-event-orchestrator.md`). Code: `backend/src/gold_trading/risk/blocks.py`, `storage/risk_blocks.py` (4a); `risk/fast_lane.py` (4b), `risk/spread_lane.py` (4c), `risk/fast_lane_loop.py` (4d).

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

## 4. Spread giãn mạnh (4c — 2026-11-14)

Code: `backend/src/gold_trading/risk/spread_lane.py` (`spread-lane-2026.11.14`). Dữ liệu: giá theo giây từng nguồn giá (`quote_seconds`, ING-08), chỉ giây đã biết tại lúc xét (`available_at <= now`).

| Luật | Giá trị |
| --- | --- |
| Mốc | trung vị spread cuối giây trong 60 phút **trước giây bắt đầu đợt giãn**, cùng nguồn, bỏ giây lịch đóng cửa, cần ≥ 60 giây; **giữ nguyên suốt đợt giãn** |
| Chặn | spread lớn nhất trong giây > **3 ×** mốc, mọi giây liên tục **≥ 5 giây** → `SPREAD` / `SPREAD_WIDE`, phạm vi = đúng nguồn giá đó, không giờ hết |
| Gỡ | sau lúc chặn, spread < **1,5 ×** mốc (lúc chặn) liên tục ≥ **2 phút** và giá còn mới (≤ 10 giây) → gỡ, `lifted_at` = lúc hệ thống biết |
| Giá cũ / mất giá | không gỡ, không kết luận "chưa đủ mốc"; nhưng **giây giãn đến trễ vẫn gây chặn** (an toàn) |
| Chưa đủ mốc (vừa mở cửa, nguồn mới) mà đang có giá | `SPREAD_UNRATED` — **tự chọn theo hướng an toàn, DEC-20 chưa nói tới**: không biết spread có bình thường không → chặn; gỡ theo cùng luật khi đã có mốc (thường ~3 phút sau giờ mở cửa) |
| 1,5–3 × | không chặn mới, không gỡ |

Tìm đầu đợt giãn: lùi từng giây (tối đa 10 phút — đợt dài hơn đã bị chặn từ giây thứ 5), mốc tính trượt bằng danh sách đã sắp; dừng khi gặp giây rõ ràng bình thường (≤ 2 × mốc của nó).

**Lỗi tìm được khi soát lại (đã sửa trước khi đưa lên):** bản đầu lấy mốc tại giây mới nhất → chính các giây đang giãn nằm trong cửa sổ 60 phút kéo trung vị từ 20 lên 22, giây 65 (> 3 × 20) bị coi là bình thường → **bỏ sót một đợt giãn 11 giây**. Sửa: mốc tại giây bắt đầu đợt giãn. Có test tái hiện (`test_wide_seconds_do_not_raise_their_own_baseline`) + test so cách tính nhanh với tính lại cả giờ cho từng giây.

**Giới hạn:** sau một đợt giãn dài (vd. 20 phút), trung vị 60 phút có thể nhích lên (20 → 22) → ngưỡng 3 × cao hơn một chút trong giờ sau đó (đúng định nghĩa DEC-20 "trung vị 60 phút"). Giá trị 3 × / 1,5 × / 5 giây / 2 phút chưa hiệu chỉnh trên dữ liệu thật.

**Kiểm chứng:** `tests/test_spread_lane.py` 23 test (bộ nhớ + SQLite). Soát lại: mô phỏng ngẫu nhiên từng giây (giãn / lưng chừng / yên, mất giây), 24 lần × 30 phút, vòng 2 giây, so với cách tính độc lập (mốc tại giây bắt đầu, tính lại cả giờ): không chặn sai, không gỡ sớm, không bỏ sót chuỗi giãn ≥ 7 giây, không bao giờ > 1 lệnh cấm mở / nguồn.

## 5. Vòng 2 giây + ngân sách độ trễ (4d — 2026-11-14)

Code: `backend/src/gold_trading/risk/fast_lane_loop.py`, `orchestrator/runner.py` (nhịp 2 giây).

- **Hai làn báo nhịp** cho `FastLaneMonitor`: `spread` (luồng riêng, mỗi 2 giây xét mọi nguồn giá MT5 đang có tài khoản dùng; `GT_FAST_LANE=0` tắt) và `events` (Event Orchestrator nay chạy **2 giây / nhịp** thay vì 10, job `FAST_LANE`).
- **Ngân sách 10 giây (DEC-20 câu 4, 2-C09)** — Safety thêm lệnh cấm `LATENCY` (tính khi đọc, phạm vi mọi nguồn, không giờ hết, tự hết khi hết nguyên nhân):

| Mã | Khi nào |
| --- | --- |
| `FAST_LANE_STARTING` | làn đã bật mà chưa chạy xong lần nào |
| `FAST_LANE_STALLED` | lần chạy xong gần nhất cũ hơn 10 giây (lỗi DB, luồng treo, đồng hồ máy chủ bị chặn, một vòng chạy quá 10 giây thì không tính là xong) |
| `FAST_LANE_BACKLOG` | có sự kiện làn nhanh đã biết quá 10 giây mà job chưa xong (bộ xử lý lỗi đang thử lại…) |

- Lệnh cấm ghi với `latency_ms` > 10 giây → log cảnh báo + đếm `budget_breaches` (sự kiện cũ xử lý lại lúc khởi động — lệnh cấm đã hết hạn — không tính).
- **Băng cảnh báo web** (trang Tổng quan): "Đang chặn mở lệnh mới" + mỗi cửa sổ gộp một dòng: lý do tiếng Việt + "tới <giờ>" hoặc "tới khi hết nguyên nhân" + nhắc công tắc Safety không đổi, thao tác bảo vệ vẫn làm được.
- Đo trên Postgres 16: nhịp orchestrator ~20 ms, vòng spread ~50 ms / nguồn (4.500 giây giá).

**Kiểm chứng:** `tests/test_fast_lane_loop.py` 7 test + `frontend/.../EntryBlockBanner.test.tsx` 2 test. Soát lại bằng luồng thật, thời gian thật: kho giá lỗi → Safety chặn sau 10,0 giây, hồi phục → tự mở; orchestrator dừng → chặn sau 10,0 giây.
