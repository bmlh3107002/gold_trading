# Thiết kế — Event Orchestrator: nhật ký sự kiện + job (GĐ2 bước 1 — ORC-03, ORC-06, ORC-08)

> Tạo 2026-11-13. Đặc tả `docs/huong-dan-chuc-nang/03-event-orchestrator.md`. Code: `backend/src/gold_trading/orchestrator/`. Migration 0014.

## 1. Nguyên tắc

- **Sự kiện suy ra từ dữ liệu đã lưu** (nến, `external_records`) theo thời điểm hệ thống **biết** (`known_at`), không móc vào code nạp. Cùng dữ liệu → cùng sự kiện, cùng khóa → nạp lại / quét lại / replay không sinh thêm (2-C01, Gate GĐ2).
- **Chỉ thêm** (trigger chặn UPDATE / DELETE như các bảng khác). Trạng thái job **không lưu đè** — tính từ nhật ký lần thử mới nhất (như ING-30) → restart không mất, không chạy lại job đã xong (ORC-08, 2-C05).
- Orchestrator **không** đưa ra nhận định thị trường; chỉ điều phối.

## 2. Sự kiện (`orchestrator_events`)

| Cột | Ý nghĩa |
| --- | --- |
| `event_id` | `sha256(event_type | subject | event_version)[:40]` — **duy nhất**; ghi lại → bỏ qua |
| `event_type` | xem bảng dưới |
| `subject` | chủ thể (nguồn giá / dữ kiện) |
| `event_version` | phiên bản của chủ thể (giờ mở nến + revision; revision bản ghi ngoài) |
| `occurred_at` | thời điểm sự kiện ngoài đời (giờ đóng nến, `event_time`) |
| `known_at` | lúc hệ thống biết (`max(ingested_at, available_at)` của dữ liệu gốc) — **thứ tự nhân quả** |
| `recorded_at` | lúc bộ quét ghi (chỉ để quan sát; không dùng cho quyết định) |
| `correlation_id` | = `event_id` của sự kiện gốc; job con mang theo (ORC-06) |
| `payload` | tham chiếu nhỏ (khóa bản ghi gốc, cờ) — không chép dữ liệu |

| `event_type` | Từ đâu | `subject` / `event_version` |
| --- | --- | --- |
| `CANDLE_CLOSED` | nến đã đóng (mọi khung, mọi nguồn giá) | `source:feed_id:symbol:timeframe` / `open_time` ISO + `:r<revision>` |
| `CALENDAR_UPDATED` | bản ghi `kind=calendar` | `source:logical_key` / `r<revision>` |
| `ACTUAL_RELEASED` | số actual (`bea_nipa`, `dol_claims`, `bls_values`) | như trên |
| `MACRO_UPDATED` | `fed_h15` (+ chỉ số USD tính từ nến — qua `CANDLE_CLOSED`) | như trên |
| `POSITIONING_UPDATED` | `cftc_cot_gold` | như trên |
| `NEWS_PUBLISHED` | `kind=news` | như trên |

**Thứ tự** (2-C02): `(known_at, event_type, subject, event_version)` — toàn phần, ổn định khi replay dù thứ tự ghi khác.

**Quét:** mỗi nhịp đọc dữ liệu có `known_at` trong `(mốc − 15 phút chồng lấn, now]`, ghi sự kiện theo khóa (trùng → bỏ qua). Mốc = `known_at` lớn nhất đã ghi của luồng đó (tính từ bảng sự kiện, không lưu riêng). Chồng lấn bắt bản ghi commit chậm có `known_at` hơi cũ. Dữ liệu có `known_at` ở tương lai (vd. COT nạp trước giờ công bố) chỉ thành sự kiện khi tới giờ.

## 3. Job (`orchestrator_jobs` + `orchestrator_job_attempts`)

- `job_key = event_type|subject|event_version|job_type@analyzer_version` (ORC-03) — **khóa chính** của `orchestrator_jobs` (tạo job = chèn; trùng → đã có, không tạo lại).
- Nhật ký lần thử (chỉ thêm): `state` ∈ `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `DEAD` (dead-letter), `NO_HANDLER` (loại job chưa có bộ xử lý — analyst GĐ3; không giả kết quả), `SUPERSEDED` (debounce: có sự kiện mới hơn cùng chủ thể); `attempt`, `at`, `deadline_at`, `error_code` (mã ngắn, như ING-30), `output_ref`.
- Trạng thái hiện tại = dòng mới nhất theo `(at, seq)`. Đã `SUCCEEDED` / `DEAD` / `NO_HANDLER` / `SUPERSEDED` → không chạy lại (kết thúc). `RUNNING` quá `deadline_at` (vd. backend tắt giữa chừng) → coi là lần thử thất bại `DEADLINE_EXCEEDED`, xét retry (2-C05).
- Retry / backoff / dead-letter, debounce, bảng sự kiện → job: bước 2.

## 4. Bộ quét (1c — `orchestrator/scanner.py`, 2026-11-13)

- Hai luồng: **nến** (`candle_store.known_between`: `lo < max(ingested_at, available_at) <= now`, chỉ nến mở trong 60 ngày — Gateway nạp bù tối đa ~52 ngày, cắt chunk hypertable) và **bản ghi ngoài** (`record_store.known_between`: `lo < known_at <= now`, mọi revision).
- Mốc `lo` = `known_at` lớn nhất đã ghi của luồng − 15 phút (chồng lấn bắt bản ghi commit chậm). Chưa có sự kiện nào → 2 ngày gần nhất (không dựng lại cả lịch sử khi bật lần đầu). Replay: truyền `since` → quét từ mốc chỉ định.
- Loại sự kiện ngoài theo `kind` / nguồn: `calendar` → `CALENDAR_UPDATED`; `news` → `NEWS_PUBLISHED`; `positioning` → `POSITIONING_UPDATED`; `bea_nipa` / `dol_claims` / `bls_values` / `census_marts` → `ACTUAL_RELEASED`; còn lại (`fed_h15`) → `MACRO_UPDATED`.
- `payload` chỉ tham chiếu: `source`, `logical_key`, `revision`, `record_id` (+ `event`, `series`, `release_ref`, `status` nếu có, ≤ 128 ký tự); nến: `open_time`, `revision`, cờ.
- **Giới hạn đã biết:** bản ghi có `known_at` cũ hơn mốc quá 15 phút mà ghi sau lần quét (commit chậm > 15 phút) bị bỏ sót ở chế độ thường — replay có `since` bắt được. Chi phí: ngay sau một lần nạp bù lớn (35.000 nến) mỗi lần quét trong 15 phút kế tiếp mất ~2 giây (kiểm lại khóa); bình thường vài chục dòng.
- **Kiểm chứng:** `tests/test_orchestrator_scanner.py` 13 test (bộ nhớ + SQLite): 12 việc thật của bộ chạy GĐ1 → đủ 5 loại sự kiện ngoài, quét lại không thêm; nến + sửa nến → sự kiện revision mới; COT nạp sớm chỉ thành sự kiện lúc 20:30 UTC công bố; lần đầu 2 ngày, replay có mốc đủ; quét 7 phút / lần = một lần replay (cùng nhật ký, cùng thứ tự); chồng lấn bắt commit chậm. **Soát lại** (Postgres 16): 7 cặp × 5.000 nến nạp bù + toàn bộ nguồn ngoài → 35.327 sự kiện trong 2,5 giây, Postgres = bộ nhớ cùng thứ tự, quét lại 40 giây sau không thêm.

## 5. Bộ điều phối (bước 2 — `orchestrator/dispatcher.py`, 2026-11-14)

**Định tuyến** (`ROUTER_VERSION = router-2026.11.14`, đặc tả 03):

| Sự kiện | Job | Debounce |
| --- | --- | --- |
| `CANDLE_CLOSED` vàng (`XAU…`) M15 | `TECHNICAL`, `REGIME` | có |
| `CANDLE_CLOSED` cặp USD M15 | `MACRO` | có |
| `CANDLE_CLOSED` khung khác | — | |
| `ACTUAL_RELEASED` | `FAST_LANE`, `EVENT_CALENDAR` | **không** |
| `CALENDAR_UPDATED` | `EVENT_CALENDAR` | không |
| `MACRO_UPDATED` | `MACRO` | có |
| `POSITIONING_UPDATED` | `POSITIONING` | không |
| `NEWS_PUBLISHED` | `FAST_LANE`, `NEWS` | **không** |

- Loại job chưa có bộ xử lý (hiện: mọi loại trừ khi được đăng ký — Technical nối ở bước 3, làn nhanh bước 4, analyst khác GĐ3) → `NO_HANDLER` ngay, **không giả kết quả**. `job_key` mang phiên bản bộ xử lý (`none` khi chưa có) → khi có bộ xử lý / đổi phiên bản, sự kiện trong 2 ngày gần nhất có job mới; job phiên bản cũ không chạy bằng code mới.
- **Debounce** (ORC-04, 2-C03): job `PENDING` có cùng loại + cùng chủ thể mà có sự kiện mới hơn (theo `occurred_at`, rồi phiên bản) → `SUPERSEDED`. Nạp bù 20 nến → Technical chạy 1 lần cho nến mới nhất; 20 công bố → chạy đủ 20.
- **Chạy theo thứ tự nhân quả** của sự kiện. Mỗi lần thử: `RUNNING` (kèm `deadline_at`) → `SUCCEEDED` / `FAILED` / `DEAD`. Mặc định deadline 30 giây, tối đa 3 lần, backoff 10 s × 2^(n−1) (trần 5 phút); lỗi thuộc loại "không thử lại" → `DEAD` ngay. Chạy xong mà quá deadline → **không dùng kết quả**, tính là thất bại `DEADLINE_EXCEEDED` (2-C04). Mã lỗi = tên loại lỗi viết hoa (vd. `RUNTIME_ERROR`), không bao giờ đọc thông điệp.
- **Khởi động lại** (2-C05): nạp lại job chưa kết thúc tạo trong 2 ngày (chỉ mục `orchestrator_jobs.created_at`, migration 0015). `RUNNING` chưa quá deadline → chờ (không chạy song song); quá deadline → `FAILED DEADLINE_EXCEEDED` rồi xét retry.
- **Replay:** cùng nhật ký sự kiện + cùng lịch nhịp → cùng job, cùng trạng thái. Lịch nhịp khác (một nhịp vs nhiều nhịp) chỉ khác ở các job được debounce (nến trung gian `SUPERSEDED` hay đã chạy); job công bố / lịch / tin luôn chạy đủ.
- **Kiểm chứng:** `tests/test_orchestrator_dispatcher.py` 22 test (bộ nhớ + SQLite): định tuyến, mã lỗi chỉ từ loại lỗi (thông điệp chứa khóa không lọt), không nhân đôi + khởi động lại không chạy lại, `correlation_id`, thứ tự nhân quả khi sự kiện tới ngược, debounce theo chủ thể và không bao giờ cho công bố, retry + backoff đúng giây, dead-letter sau 2 / 3 lần và lỗi không thử lại, quá deadline → không dùng kết quả, chết giữa lúc chạy → chờ deadline rồi thử lại, đổi phiên bản bộ xử lý, replay một nhịp vs nhiều nhịp. **Soát lại** (kịch bản riêng): 40 kịch bản ngẫu nhiên (60 sự kiện tới xáo trộn, bộ xử lý lỗi 35 %, khởi động lại 10 % số nhịp) + 1 trên Postgres 16 — bất biến giữ: mỗi `job_key` một job; sau trạng thái kết thúc không ghi thêm; ≤ 3 lần chạy; ≤ 1 lần thành công; `RUNNING` luôn được nối bằng kết quả; job công bố không bao giờ `SUPERSEDED` và cuối cùng đều `SUCCEEDED` / `DEAD`; `FAILED` / `DEAD` luôn có mã ngắn.
- **Chưa làm:** chạy tự động trong backend + thay runner Technical (bước 3); "analyst coi là MISSING khi job DEAD" phía người dùng output (Quality Gate GĐ4 — ghi chú 2-C04).
