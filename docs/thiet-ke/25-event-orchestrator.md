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
