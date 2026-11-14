# 27 — Khung chung cho analyst (GĐ3 bước 1 — ANA-01; 3-C01..C07)

> Tạo 2026-11-14. Kế hoạch: `docs/ke-hoach/GD3-ke-hoach.md` bước 1. Code: `backend/src/gold_trading/analysts/framework.py`, `storage/analyst_outputs.py` (phần phạm vi). Test: `tests/test_analyst_framework.py`.

## 1. Vấn đề

Technical (GĐ0–1) là analyst duy nhất và gắn với **một nguồn giá** (`symbol`, `timeframe`, `source`, `feed`). Các analyst GĐ3 có hai loại:

| Loại | Analyst | Phạm vi kết quả |
| --- | --- | --- |
| Theo nguồn giá | Technical, Regime | `(symbol, timeframe, source, feed)` — mỗi broker một chuỗi riêng (MT-05) |
| Toàn cục | Event (lịch), Macro, Positioning, News | một chuỗi chung cho mọi tài khoản — đầu vào là nguồn ngoài (BLS, Fed, CFTC…), không phụ thuộc broker |

Mỗi analyst lại tự viết phần kiểm đầu vào (thiếu / cũ / thiếu lịch sử / spike / SAMPLE), cách đặt `output_id`, cách chặn đặc trưng khi dữ liệu hỏng → dễ lệch nhau. Khung chung gom những phần này.

## 2. Phạm vi lưu (`Scope`) — không cần migration

Bảng `analyst_outputs` (đã **chỉ-thêm**: trigger 0003, duy nhất theo `(feed_id, output_id)` 0010) có sẵn cột chuỗi `symbol`, `timeframe`, `source`, `feed_id`. Analyst toàn cục dùng **giá trị quy ước**:

| Cột | Theo nguồn giá | Toàn cục (`GLOBAL_SCOPE`) |
| --- | --- | --- |
| `symbol` | `XAUUSD` | `*` |
| `timeframe` | `M15` | `*` |
| `source` | `SAMPLE` / `CSV` / `MT5` | `GLOBAL` |
| `feed_id` | id nguồn giá | `""` |

Lý do không thêm cột / migration: đủ phân biệt, không đổi dữ liệu cũ, không đụng TimescaleDB (bài học 0009). `*` và `GLOBAL` không trùng được giá trị thật (`Timeframe`, `DataSource` là enum không có các giá trị này — test chặn).

Hệ quả đã kiểm:
- `expired_unreplaced` (ORC-07) và `computed_between` (replay) chỉ so chuỗi → chạy đúng cho phạm vi toàn cục; chủ thể sự kiện hết hạn `event:GLOBAL::*:*`. Bộ định tuyến **chưa** cho tính lại analyst toàn cục khi hết hạn (chỉ `TECHNICAL`) — thêm ở bước 2 cùng bộ xử lý `EVENT_CALENDAR` (đổi `ROUTER_VERSION`).
- `latest(...)` cũ (Technical) giữ nguyên chữ ký; thêm `append_scoped` / `latest_scoped` dùng `Scope`.

## 3. `output_id` — xác định, có phiên bản (3-C07)

`output_id = "<analyst>:<version>:<scope.key>:<as_of ISO>:<16 ký tự đầu sha256 đầu vào>"`.

- Cùng phiên bản + cùng thời điểm + cùng đầu vào → cùng id → ghi lại bị bỏ qua (idempotent; replay không nhân đôi).
- Đổi công thức / ngưỡng → **phải tăng `version`** → id mới, kết quả cũ giữ nguyên (chỉ-thêm).
- `input_digest`: sha256 của JSON chuẩn (`sort_keys`, không khoảng trắng); chỉ nhận kiểu JSON thuần + `datetime` có múi giờ (đổi về UTC ISO) — kiểu lạ / datetime không múi giờ → lỗi (không âm thầm `str()`).

## 4. Kiểm đầu vào (`InputCheck` → `assess`) — 3-C01..C05

Mỗi đầu vào khai báo: tên, bắt buộc hay không, `known_at` của bản ghi mới nhất **đã biết tại `as_of`**, tuổi tối đa, số mẫu lịch sử / tối thiểu, số điểm cực đoan, có phải SAMPLE.

| Tình huống | Đầu vào bắt buộc | Đầu vào tùy chọn |
| --- | --- | --- |
| Không có (`known_at = None`) — 3-C01 | `MISSING`, chặn: `MISSING_INPUT:<tên>` | cờ chất lượng `OPTIONAL_MISSING:<tên>` |
| Quá cũ (`as_of − known_at > max_age`, hoặc `healthy=False` — nguồn không khỏe theo ING-30) — 3-C02 | `STALE`, chặn: `STALE_INPUT:<tên>` | cờ `OPTIONAL_STALE:<tên>` |
| Chưa đủ lịch sử — 3-C03 | `INVALID`, chặn: `INSUFFICIENT_HISTORY:<tên>` | cờ `OPTIONAL_INSUFFICIENT_HISTORY:<tên>` |
| Có điểm cực đoan — 3-C04 | cờ `SPIKE_IN_INPUT:<tên>`, trần confidence × 0,5 (như Technical) | như bắt buộc |
| SAMPLE — 3-C05 | cờ `SAMPLE_DATA` | như bắt buộc |
| `known_at > as_of` | **lỗi lập trình → ném lỗi** (nhìn trước tương lai), job thử lại rồi vào dead-letter — không âm thầm cho qua |

Ưu tiên trạng thái khi nhiều lỗi: `MISSING` > `STALE` > `INVALID`. Mọi lý do chặn đều ghi vào `drivers` + `quality_flags`.

Đầu vào tùy chọn hỏng **không** tự hạ confidence trong khung (hệ số hạ là chính sách riêng từng analyst, ghi ở thiết kế analyst đó, có phiên bản) — khung chỉ gắn cờ để không bịa con số chung.

## 5. Dựng kết quả (`build_output`)

- Có lý do chặn → **không xuất đặc trưng** (3-C01): `features = {"input": <thông tin đầu vào để truy vết>}`, `confidence = 0`, `drivers = lý do`. Đặc trưng analyst đưa vào bị bỏ qua dù đã tính.
- Không chặn → `confidence = min(confidence analyst đưa, trần từ đánh giá)`; `confidence` luôn là **chất lượng dữ liệu**, không phải xác suất.
- `expires_at > as_of` (hợp đồng đã kiểm); `features` đi qua JSON để chắc lưu được.
- `features["input"]` luôn có: phạm vi, tóm tắt từng đầu vào (tên, `known_at`, tuổi giây, số mẫu), `input_digest` → mỗi output truy được về đầu vào (Gate GĐ3).

## 6. Bộ test chung (3-C06, 3-C07 + 3-C01..C05)

`tests/test_analyst_framework.py`: một analyst mẫu tối giản dùng khung, kiểm: thiếu / cũ / thiếu lịch sử / spike / SAMPLE / tùy chọn hỏng; thêm dữ liệu "tương lai" (known_at > as_of) vào kho rồi tính lại tại thời điểm cũ → cùng kết quả (3-C06); đổi phiên bản → id mới, kết quả cũ còn (3-C07); kho bộ nhớ + SQLite + (soát) Postgres cho `append_scoped` / `latest_scoped` / `expired_unreplaced` với phạm vi toàn cục. Analyst GĐ3 sau dùng lại cùng mẫu kiểm.
