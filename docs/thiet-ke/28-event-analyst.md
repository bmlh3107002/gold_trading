# 28 — Analyst Lịch sự kiện (GĐ3 bước 2 — EVT-01..04; 3-C08, 3-C09)

> Tạo 2026-11-14. Kế hoạch: `docs/ke-hoach/GD3-ke-hoach.md` bước 2. Code: `backend/src/gold_trading/analysts/event.py`. Test: `tests/test_event_analyst.py`. Khung chung: `27-khung-analyst.md`. Đặc tả: `docs/huong-dan-chuc-nang/04-cac-analyst.md` mục 3.

## 1. Vai trò — chỉ quan sát

- **Không chặn lệnh.** Chặn mở lệnh mới quanh công bố vẫn chỉ do Safety / làn nhanh (DEC-20, `26-lam-nhanh.md`). Analyst mô tả trạng thái lịch cho Fusion / Strategy / Risk (GĐ4–5) và giao diện.
- **Một nguồn sự thật cho cửa sổ:** analyst gọi đúng `economic_calendar` (cùng trạng thái nguồn ING-30) + `fast_lane.calendar_blocks` + `merge_windows`. Tại cùng `as_of`, tập lý do đang hiệu lực của analyst = phần lịch của Safety (`CalendarBlocks`) — có test quét > 200 thời điểm quanh CPI + soát riêng.
- **Không gồm:** lệnh cấm đã lưu của job `FAST_LANE` (thông cáo Fed ngoài lịch, số đến trễ quá khung tra cứu 24 giờ) — phần đó là tin / làn nhanh; News analyst (bước 6) sẽ mô tả tin.
- Không LLM. Mức quan trọng + độ dài cửa sổ: bảng có phiên bản `event_importance.POLICY_VERSION` (GĐ1, không viết lại). Phiên bản chính sách ghi trong `features.policy`.

## 2. Đầu vào (khung chung, `GLOBAL_SCOPE`)

| Đầu vào | Bắt buộc | Thiếu / hỏng |
| --- | --- | --- |
| 4 nguồn lịch: `fed_fomc`, `bea_schedule`, `dol_claims_schedule`, `bls_schedule` | có | **Không có lịch nào phủ quá `as_of + 24 giờ`** → `MISSING` (lịch rỗng **không** có nghĩa là "không có rủi ro"). Nguồn không khỏe (ING-30) → `STALE`. Cả hai: chặn, không xuất đặc trưng |
| 4 nguồn số actual (`bea_nipa`, `bls_values`, `dol_claims`, `census_marts`) | không | Chỉ cờ `OPTIONAL_*`; trạng thái số từng sự kiện vẫn hiện (`UNKNOWN_SOURCE_DOWN`, …) |
| Nhật ký kiểm nguồn (`check_log`) | — | Không có (chỉ khi chạy thử / test) → cờ `SOURCE_HEALTH_UNKNOWN`, không bịa thời điểm kiểm |

Đọc lỗi → ném lỗi → job thử lại → dead-letter (không giả kết quả). Point-in-time: mọi bản ghi lấy qua `store.as_of(as_of)`; thêm dữ liệu biết sau `as_of` không đổi kết quả (3-C06, có test).

## 3. Đặc trưng (`features`)

| Khóa | Ý nghĩa |
| --- | --- |
| `event_risk` | Mức cao nhất trong các cửa sổ đang hiệu lực: `HIGH` / `MEDIUM` / `LOW` / `NONE` (`RELEASE_HIGH_RECEIVED` → `HIGH`) |
| `window` | Cửa sổ gộp đang chứa `as_of` (`start`, `end`, `reasons`, `causes`) hoặc `null` |
| `active_reasons` | Mã lý do đang hiệu lực — trùng phần lịch của Safety |
| `next_event`, `upcoming` | Sự kiện kế tiếp / trong 24 giờ: tên, mức, giờ công bố, cửa sổ, giờ đã xác nhận hay cả ngày, `minutes_until`, `revision` |
| `soon` | Có cửa sổ bắt đầu trong 60 phút tới |
| `recent_releases` | Công bố trong 24 giờ qua: `actual_status` (`NOT_DUE` / `AWAITING` / `RECEIVED` / `UNKNOWN_LATE` / `UNKNOWN_SOURCE_DOWN`), `actuals` (**chuỗi gốc của nguồn** — "0" là số 0, khác "chưa công bố"), `forecast_status` + `surprise_status` = `INSUFFICIENT_DATA` (DEC-01) |
| `removed` | Sự kiện bị gỡ khỏi lịch (hủy / dời) trong khoảng tra cứu (EVT-04) |
| `schedule_coverage_until` | Lịch mỗi nguồn phủ tới đâu (giải thích `MISSING`) |
| `input` | Truy vết (khung chung): phạm vi, băm đầu vào, tình trạng từng nguồn |

Cờ rủi ro: `EVENT_WINDOW` (đang trong cửa sổ), `EVENT_SOON`. Driver: `EVENT_RISK_<mức>`, `IN_EVENT_WINDOW`, `EVENT_SOON:<sự kiện>`, `ACTUAL_UNKNOWN:<sự kiện>`, `EVENT_REMOVED:<sự kiện>`, `CALENDAR_SOURCES_DISAGREE`, `SURPRISE_INSUFFICIENT_DATA`.

**Không có xác suất, không có hướng bất ngờ** (chưa có forecast). `confidence` = chất lượng dữ liệu: 1,0; nguồn lịch mâu thuẫn (`CALENDAR_SOURCES_DISAGREE`, 3-C08) trong tầm nhìn → trần 0,5 (giá trị khởi đầu, chưa hiệu chỉnh) + cửa sổ cả ngày (chính sách GĐ1).

## 4. Tình huống

- **EVT-04 hoãn / hủy / đổi giờ:** bản sửa lịch (revision) được biết → dùng giờ mới từ lúc biết; trước đó vẫn giờ cũ (point-in-time). Bị gỡ → vào `removed`, không có cửa sổ.
- **3-C09 công bố lúc thị trường đóng:** giữ 15 phút sau khi nhận số HIGH tính bằng **phút thị trường mở** (`hold_end`, như làn nhanh) — số nhận 2 phút trước giờ đóng thứ Sáu → 13 phút còn lại tính từ giờ mở Chủ nhật.
- **Đổi giờ DST:** giờ công bố đã đổi về UTC ở GĐ1 (nguồn + `_day_window` 23 / 25 giờ có test riêng); analyst chỉ dùng UTC.
- **Số đến trễ hơn 24 giờ:** ngoài khung tra cứu của cả analyst lẫn `CalendarBlocks` (cùng hành vi); Safety vẫn chặn nhờ lệnh cấm đã lưu của job `FAST_LANE`.

## 5. Chạy + hết hạn

- `as_of = max(now − 5 giây, lúc biết sự kiện)` (bản ghi commit chậm vẫn được thấy; sự kiện vừa biết luôn được tính).
- `expires_at` = mốc gần nhất làm kết quả đổi (mở / đóng cửa sổ, giờ công bố, 60 phút trước cửa sổ), chậm nhất **15 phút** (trạng thái nguồn đổi không sinh sự kiện); kết quả bị chặn: **2 phút**.
- Job `EVENT_CALENDAR` (đã có định tuyến từ GĐ2: lịch đổi, số actual mới) + **mới:** kết quả `event` hết hạn → `OUTPUT_EXPIRED` → tính lại (`ROUTER_VERSION` → `router-2026.11.14c`). Đã có kết quả còn hạn tính sau lúc biết sự kiện → bỏ qua (nạp bù trăm bản ghi không sinh trăm kết quả).
- **Dự phòng** mỗi nhịp orchestrator: không có kết quả còn hạn quá 60 giây (lần chạy đầu, chuỗi hết hạn bị đứt) → tính ngay.
- Lưu chỉ-thêm, idempotent theo `output_id` (phiên bản + `as_of` + băm đầu vào). Đổi công thức / ngưỡng → tăng `VERSION` (`event-1.0.0`).

## 6. Giá trị chưa hiệu chỉnh

`SOON` 60 phút, trần confidence 0,5 khi mâu thuẫn, TTL 15 / 2 phút: chọn theo hướng an toàn / đủ tươi, **chưa hiệu chỉnh** trên dữ liệu thật; xem lại ở GĐ4–6 khi Fusion / backtest dùng tới.
