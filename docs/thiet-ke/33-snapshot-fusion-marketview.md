# 33 — Snapshot → Quality Gate → Fusion → MarketView (GĐ4)

> Tạo 2026-11-15 (GĐ4 bước 1a). Kế hoạch: `docs/ke-hoach/GD4-ke-hoach.md`. Đặc tả: `docs/huong-dan-chuc-nang/05-snapshot-fusion-marketview.md`. Quyết định người dùng: DEC-24..27 (`docs/giai-doan/GD4-snapshot-fusion-marketview.md`). Các mục ghi "bước n" được chốt chi tiết (kèm test) ở bước đó; sửa ở đây cùng commit.

## 1. Nguyên tắc

- **Theo nguồn giá (MT-05 / DEC-14).** Mỗi nguồn giá `(symbol, timeframe, source, feed)` có chuỗi MarketView riêng. Không trộn giá giữa các broker.
- **Point-in-time.** Tại thời điểm `at` chỉ dùng output analyst **đã ghi trước `at`** (`known_by = at`) và còn hiệu lực (`as_of ≤ at < expires_at`). Thêm output "tương lai" vào kho rồi dựng lại tại `at` cũ → cùng kết quả.
- **Không bịa số.** `pUp` / `pDown` = `null` cho tới khi có hiệu chỉnh thật (DEC-27). `confidence` = chất lượng dữ liệu × mức đồng thuận, **không phải xác suất đúng**. Mọi ngưỡng / hệ số dưới đây là **giá trị khởi đầu chưa hiệu chỉnh**.
- **Chưa kiểm chứng thì không cho giao dịch thật.** Mọi MarketView GĐ4 mang `UNVALIDATED_RULES` + `UNCALIBRATED` (hợp đồng bắt buộc); Risk chặn ở SHADOW/LIVE (DEC-25, bước 5). Gỡ cờ = quyết định mới của người dùng sau backtest GĐ6, sửa hợp đồng + ghi vào file giai đoạn.
- **Fusion chỉ mô tả, không chặn.** Chặn mở lệnh vẫn do Safety / làn nhanh (DEC-20) và Risk.

## 2. Đầu vào theo phạm vi

| Analyst | Phạm vi (thiết kế 27) | Vai trò (DEC-24) | Dùng trong Fusion |
| --- | --- | --- | --- |
| Technical | theo nguồn giá | **bắt buộc** | `trend`, `mtf_alignment`, `vol_forecast` |
| Regime | theo nguồn giá | **bắt buộc** | `regime`, `direction`, `ambiguous` |
| Event (lịch) | toàn cục | **bắt buộc** | cờ `EVENT_WINDOW` / `EVENT_SOON` |
| Macro | theo nguồn giá vàng | tùy chọn | `macro_bias` |
| Positioning (COT) | toàn cục | tùy chọn | `crowding` |
| News | toàn cục | tùy chọn | `tone_score` (chỉ khi chế độ LLM; chế độ luật → `null` = không đánh giá) |

## 3. Snapshot (bước 2)

- Mỗi analyst: output mới nhất `latest_scoped(scope, known_by=at)` còn hiệu lực tại `at`. **Phạm vi kiểm bằng cột trong kho** (`symbol / timeframe / source / feed_id`), không qua `output_id`: Technical có id kiểu cũ không chứa feed (soát 5b). Không có → vắng mặt (Quality Gate quyết).
- `available_at = at`; `event_time = max(as_of)` các output đã chọn; `expires_at = min(expires_at)` các output **bắt buộc** đã chọn.
- `input_manifest = {analyst: output_id}` (+ phiên bản). Output analyst đã **chỉ-thêm** (trigger 0003) → tái dựng được từ manifest; mất một output → tái dựng **báo lỗi**, không đoán.
- `snapshot_id` xác định: `snap:<scope.key>:<16 ký tự sha256(manifest)>` → cùng đầu vào cùng id (idempotent khi replay).
- Bất kỳ đầu vào nào từ `SAMPLE` → cờ `SAMPLE_DATA` (4-C06).
- Lưu bảng `market_snapshots` chỉ-thêm (migration 0018); không chép lại `features` của analyst (đã có ở `analyst_outputs`). Phiên bản analyst nằm sẵn trong `output_id` (thiết kế 27 mục 3).
- **Đã làm (bước 2, `snapshot-1.0.0`):** output mới nhất đã biết mà **hết hạn** → không lùi về bản cũ hơn (bản cũ hết hạn sớm hơn), ghi vào `excluded_inputs` + cờ `EXPIRED_EXCLUDED:<analyst>` để Quality Gate phân biệt "hết hạn" với "vắng". `snapshot_id` băm cả `excluded_inputs` → hai tình huống khác nhau không chung id. Cùng đầu vào ở hai thời điểm → **cùng id**; kho giữ bản đầu (`available_at` lần đầu; `expires_at` cũng là của lần đầu khi không có đầu vào bắt buộc — trường hợp này vốn bị `REJECTED`). Output sai phạm vi / sai analyst / `as_of > at` → ném lỗi.

## 4. Quality Gate — `quality-policy-1` (bước 3)

| Tình huống | Bắt buộc (Technical, Regime, Event) | Tùy chọn (Macro, Positioning, News) |
| --- | --- | --- |
| Vắng / hết hạn / analyst lỗi (dead-letter = vắng, 2-C04) | `REJECTED` `REQUIRED_MISSING:<a>` / `REQUIRED_EXPIRED:<a>` | cờ `OPTIONAL_MISSING:<a>` / `OPTIONAL_EXPIRED:<a>`, hệ số × 0,9 |
| `source_status` ≠ `HEALTHY` | `REJECTED` `REQUIRED_<STATUS>:<a>` | cờ `OPTIONAL_<STATUS>:<a>`, × 0,9 |
| Thiếu đặc trưng Fusion cần (schema, DQG-02) | `REJECTED` `REQUIRED_SCHEMA:<a>` | `OPTIONAL_SCHEMA:<a>`, × 0,9 |
| Technical và Regime **không cùng nến đóng** (`as_of` khác nhau — 4-C07) | `REJECTED` `TIMESTAMP_CONFLICT` (lần tính sau sẽ khớp) | — |
| Output có `as_of > at` | lỗi lập trình → ném lỗi (job thử lại → dead-letter) | như bắt buộc |
| Cờ đầu vào cực đoan của analyst (`SPIKE_IN_INPUT`, `EXTREME_INPUT`) | chỉ truyền dạng `<analyst>:<cờ>` vào `flags` của báo cáo → `qualityFlags` (analyst đã tự đặt trần confidence 0,5 — không hạ chồng) | như bắt buộc |

**Đã chốt (bước 3, 2026-11-15).** Lý do hệ số 0,9 (giá trị khởi đầu chưa hiệu chỉnh): thiếu một nhóm tùy chọn là mất thông tin, nhưng News **mặc định tắt** nên nếu hạ mạnh thì mọi MarketView đều thấp một cách giả tạo; 3 nhóm cùng thiếu → 0,729. Kết quả Quality Gate (`verdict`, lý do, hệ số, cờ, phiên bản chính sách, `snapshot_id`, `evaluated_at`) lưu chỉ-thêm bảng `quality_reports` (migration 0019, khóa ngoại tới `market_snapshots`) để audit (DQG-03); `report_id` băm theo snapshot + chính sách + kết quả (cùng kết quả lúc khác → cùng id, giữ lần đầu).

Schema (đúng giá trị analyst đang xuất — đối chiếu bằng mọi output thật trong bộ test): Technical `trend` ∈ {UP, DOWN, FLAT}, `mtf_alignment` ∈ {ALIGNED_UP, ALIGNED_DOWN, CONFLICT, MIXED, NOT_EVALUATED}, `vol_forecast` = `null` hoặc `{sigma_day_pct: số ≥ 0 | null}`; Regime `regime` ∈ {TREND, RANGE, RISK_OFF, HIGH_VOL}, `direction` ∈ {UP, DOWN, null}, `ambiguous` bool; Event `event_risk` ∈ {NONE, LOW, MEDIUM, HIGH}; Macro `macro_bias` ∈ {SUPPORTIVE, HEADWIND, MIXED, NEUTRAL, INSUFFICIENT_DATA}; Positioning `crowding` ∈ {CROWDED_LONG, CROWDED_SHORT, NORMAL, INSUFFICIENT_DATA}; News có khóa `tone_score` (số hoặc `null`). Analyst đổi đặc trưng → phải sửa schema + tăng phiên bản chính sách. Output tùy chọn "cũ nhưng còn hạn": TTL của chính output đã lo, không thêm luật tuổi.

## 5. Fusion — `fusion-rules-1.0.0` (bước 4, DEC-25/26)

**A. Hướng gốc chỉ từ giá.** `LONG` khi **tất cả**: Technical `trend = UP`; Regime `regime = TREND` và `direction = UP`; Regime `ambiguous = false`; `mtf_alignment ≠ CONFLICT`. `SHORT` đối xứng (`DOWN`). Ngược lại `NEUTRAL` với lý do đầu tiên khớp theo thứ tự:

| Thứ tự | Điều kiện | Driver |
| --- | --- | --- |
| 1 | Regime `RISK_OFF` / `HIGH_VOL` / `RANGE` | `REGIME_NOT_TREND:<regime>` |
| 2 | Regime mơ hồ | `REGIME_AMBIGUOUS` |
| 3 | Technical `FLAT` | `PRICE_NO_TREND` |
| 4 | Hướng Technical ≠ hướng Regime | `PRICE_REGIME_DISAGREE` |
| 5 | `mtf_alignment = CONFLICT` | `MTF_CONFLICT` |

`MIXED` / `NOT_EVALUATED` đa khung: chỉ ghi driver `MTF_<…>`, không hạ (giới hạn đã biết — xem lại ở GĐ6). Technical + Regime cùng tính từ một chuỗi nến nên được coi là **một nhóm "giá"**, không phải hai phiếu.

**B. Nhóm khác chỉ được hạ (khi hướng gốc ≠ `NEUTRAL`).** Chỉ xét output đã qua Quality Gate, còn hiệu lực, `HEALTHY`:

| Nhóm | Ngược chiều `LONG` | Ngược chiều `SHORT` | Không đánh giá |
| --- | --- | --- | --- |
| Macro | `macro_bias = HEADWIND` | `SUPPORTIVE` | `MIXED`, `NEUTRAL`, `INSUFFICIENT_DATA`, vắng |
| Positioning | `crowding = CROWDED_LONG` | `CROWDED_SHORT` | `NORMAL`, chưa đủ lịch sử, vắng |
| News | `tone_score < 0` | `tone_score > 0` | `0`, `null` (chế độ luật), vắng |

`k` = số nhóm ngược chiều. `k = 0` → hệ số 1,0; `k = 1` → hệ số **0,5** + driver `OPPOSED_BY:<nhóm>` (cùng mức trần 0,5 các analyst đang dùng cho mâu thuẫn); `k ≥ 2` → **`NEUTRAL`** + driver `ANALYSTS_DISAGREE` (4-C03), hệ số vẫn 0,5 (chốt khi code, bước 4). Nhóm tùy chọn bị Quality Gate gắn vấn đề (`OPTIONAL_*`) không được tính phản đối. Nhóm **cùng chiều không bao giờ làm tăng** confidence hay tạo hướng.

**C. Confidence.** `min(confidence Technical, Regime, Event) × hệ số Quality Gate × hệ số bước B`, làm tròn 4 chữ số. Không phải xác suất.

**D. Các trường khác.**
- `regime` = `regime` của Regime; `vol_forecast` = `vol_forecast.sigma_day_pct` của Technical (σ một ngày, %, EWMA TEC-07 — luật cố định) hoặc `null` khi Technical chưa đủ lợi suất.
- `riskFlags` = hợp `risk_flags` của mọi output trong snapshot (kể cả tùy chọn không khỏe — thêm cờ = thận trọng hơn) (`EVENT_WINDOW`, `EVENT_SOON`, `NEWS_SHOCK`, `MACRO_STRESS`, `CROWDING_RISK`, `RISK_OFF_REGIME`, `HIGH_VOLATILITY_REGIME`, …) (4-C04). **Lệnh cấm của làn nhanh không chép vào MarketView**: Risk đọc trực tiếp Safety / `allows_new_orders` lúc quyết, tươi hơn bản chép (FAST-03 đi thẳng Safety).
- `qualityFlags` ⊇ {`UNVALIDATED_RULES`, `UNCALIBRATED`} + `SAMPLE_DATA` (nếu có) + lý do Quality Gate + cờ cực đoan đầu vào.
- `drivers`: theo thứ tự A → B, mỗi driver truy được về analyst.

## 6. MarketView — hợp đồng (bước 1b, `contracts/market_view.py`)

| Trường | Ghi chú |
| --- | --- |
| `market_view_id` | xác định: `mv:<fusion version>:<scope.key>:<16 ký tự sha256(fusion version + snapshot_id + report_id)>` — cùng đầu vào + cùng kết quả Gate → cùng id, ghi lại bị bỏ qua (giữ `as_of` lần đầu). Băm `report_id` (chốt bước 4): cùng snapshot nhưng nguồn tùy chọn vừa hết hạn → báo cáo khác → MarketView khác id |
| `snapshot_id`, `symbol`, `timeframe`, `source`, `feed_id` | nguồn giá (bắt buộc — không mặc định để tránh nhầm nguồn) |
| `as_of` = `at` lúc Fusion chạy; `expires_at` = `expires_at` của snapshot, trần cứng `as_of + 30 phút` | hợp đồng kiểm `expires_at > as_of` |
| `bias` | `LONG` / `SHORT` / `NEUTRAL` — "nghiêng theo luật, chưa kiểm chứng" |
| `p_up`, `p_down` | **luôn `null` trong GĐ4** — hợp đồng từ chối số (GĐ7 đổi hợp đồng khi có registry hiệu chỉnh) |
| `confidence` | mục 5C |
| `regime` | enum `TREND` / `RANGE` / `RISK_OFF` / `HIGH_VOL` |
| `vol_forecast` | `float ≥ 0` hoặc `null` — σ một ngày, % |
| `drivers`, `risk_flags`, `quality_flags` | hợp đồng bắt buộc `quality_flags` ⊇ {`UNCALIBRATED`, `UNVALIDATED_RULES`}; `source = SAMPLE` ⇒ có `SAMPLE_DATA` |
| `model_version` | phiên bản Fusion; `quality_policy_version` | phiên bản chính sách Quality Gate |

## 7. Khi nào sinh / hết hạn / vô hiệu (bước 5)

- **Việc mỗi nhịp của orchestrator** (`FusionRunner.tick`, 5b) — chạy SAU mọi job analyst của nhịp (job `FUSION` trong bảng định tuyến sẽ chạy trước `REGIME` / `TECHNICAL` cùng sự kiện vì bộ điều phối sắp theo chữ cái); không đổi snapshot + báo cáo thì không ghi. Quality Gate `REJECTED` → không sinh MarketView (lưu báo cáo) **và vô hiệu MarketView hiện hành của nguồn giá đó** (lý do `QUALITY_REJECTED`) — nếu không, MarketView cũ tạo lúc nguồn còn khỏe vẫn dùng được tới hết hạn (tìm thấy khi thiết kế 5a).
- Lưu (5a, migration 0020): `market_views` + `market_view_invalidations` chỉ-thêm, khóa ngoại tới snapshot + báo cáo Gate. `current(nguồn giá, at)` = MarketView mới nhất đã biết, còn hạn, chưa bị vô hiệu tới `at`; ngược lại không có — không lùi về bản cũ.
- `OUTPUT_EXPIRED` → job `INVALIDATE_MARKETVIEW` (`fusion-job-1`): tính lại ngay cho nguồn bị ảnh hưởng (analyst toàn cục → mọi nguồn) → bắt buộc hết hạn thì Gate `REJECTED` → vô hiệu nếu MarketView còn hạn. Thường MarketView đã tự hết hạn cùng output bắt buộc (hạn = sớm nhất của chúng). Phía dùng chỉ lấy MarketView **còn hạn và chưa bị vô hiệu** của đúng nguồn giá; không có → không tín hiệu (2-C06).
- Strategy kiểm `expires_at` lúc tạo intent; Risk kiểm lại lúc quyết (đã có — `MARKET_VIEW_EXPIRED`) (4-C05).

## 8. Giới hạn đã biết

- Mọi ngưỡng / hệ số (0,9; 0,5; `k ≥ 2`; trần 30 phút) chưa hiệu chỉnh — xem lại ở GĐ6 (backtest) / GĐ7.
- Fusion không dùng mẫu hình nến (TEC-06), hỗ trợ / kháng cự, mức bất ngờ tin (chưa có forecast — DEC-01).
- Bảng trọng số Regime (`regime-weights-0-neutral`) không dùng để tạo hướng (DEC-26).
