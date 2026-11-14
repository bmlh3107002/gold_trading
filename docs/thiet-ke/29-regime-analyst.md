# 29 — Analyst Regime bằng luật (GĐ3 bước 3 — REG-01, REG-02)

> Tạo 2026-11-14. Kế hoạch: `docs/ke-hoach/GD3-ke-hoach.md` bước 3. Code: `backend/src/gold_trading/analysts/regime.py`, ADX: `analysts/indicators.py::adx`. Test: `tests/test_regime.py`. Khung chung: `27-khung-analyst.md`. Đặc tả: `docs/huong-dan-chuc-nang/04-cac-analyst.md` mục 6. Bản HMM / classifier: GĐ7.

## 1. Vai trò

Mô tả **trạng thái thị trường** của từng nguồn giá (mỗi broker một chuỗi — MT-05) để Fusion (GĐ4) biết nên tin nhóm tín hiệu nào. Không dự báo, không ra tín hiệu, **không có xác suất** (luật chưa hiệu chỉnh — đặc tả nói "xác suất" cho bản mô hình GĐ7).

## 2. Đầu vào

Nến M15 **đã đóng** của nguồn giá, point-in-time (`market.candles(as_of=now)`), cửa sổ `WINDOW = 1.184` nến (cần tối thiểu `MIN_BARS = 1.084`: 960 nến nền biến động + 96 nến lịch sử phân loại + 28 nến khởi động ADX). Cổng chất lượng (khung chung):

| Tình huống | Hành vi |
| --- | --- |
| Không đủ 1.084 nến | `INVALID`, `INSUFFICIENT_HISTORY:candles`, không xuất đặc trưng |
| Nến cuối trễ hơn nến lẽ ra đã đóng / giá đóng băng (300 nến gần nhất) | `STALE`, `STALE_INPUT:candles` (+ cờ `STALE_INPUT` / `FROZEN_FEED`) |
| Độ phủ 300 nến gần nhất thấp / nến ngoài giờ lịch | `INVALID`, `LOW_COVERAGE:candles` / `CALENDAR_MISMATCH:candles` |
| Độ phủ cả cửa sổ thấp (lỗ hổng cũ) | cờ `BASELINE_LOW_COVERAGE`, trần confidence 0,5 |
| Nến cực đoan trong cửa sổ | cờ `SPIKE_IN_INPUT:candles`, trần confidence 0,5 |
| SAMPLE | cờ `SAMPLE_DATA` |
| Ngày lễ / thanh khoản thấp | cờ rủi ro `LOW_LIQUIDITY_HOLIDAY` (như Technical) |

## 3. Luật phân loại (`regime-1.0.0`)

| Thứ tự | Điều kiện | Nhãn |
| --- | --- | --- |
| 1 | `vol_ratio = ATR14 / trung vị ATR14 960 nến ≥ 2,0` | `HIGH_VOL` |
| 2 | `ADX14 ≥ 25` | `TREND` (hướng: +DI > −DI → `UP`, ngược lại `DOWN`) |
| 3 | `ADX14 ≤ 20` | `RANGE` |
| 4 | `20 < ADX14 < 25` | nhãn gần hơn (≥ 22,5 → `TREND`, còn lại `RANGE`) + **mơ hồ** |

**Mơ hồ** khi ADX trong (20, 25) hoặc `vol_ratio` trong [1,8; 2,2): driver `AMBIGUOUS_REGIME`, trần confidence 0,5 (đặc tả: "confidence thấp khi các lớp gần nhau" — bản luật dùng khoảng cách tới ngưỡng thay cho xác suất).

**`RISK_OFF` chưa đánh giá** (`risk_off: NOT_EVALUATED`, driver `RISK_OFF_NOT_EVALUATED`): cần dữ liệu liên thị trường (USD, lợi suất thực) — có ở Macro analyst (bước 4). Không suy từ giá vàng một mình. Bổ sung → tăng `VERSION`.

Nguồn ngưỡng: ADX 25 / 20 là quy ước của Wilder (1978); 2× biến động như Technical (`HIGH_VOL_RATIO`, nhưng nền 10 ngày thay vì 1 ngày → hai cờ có thể khác nhau, có chủ ý: Technical mô tả "hôm nay", Regime mô tả "so với 2 tuần"); vùng mơ hồ 22,5 / [1,8; 2,2), nền 960 nến, lịch sử 96 nến: **giá trị khởi đầu chưa hiệu chỉnh**, xem lại ở GĐ6 (backtest) / GĐ7.

ADX Wilder (`indicators.adx`): khớp thư viện `ta` 0.11 (`ADXIndicator`) tới 3,6e-14 trên 20 chuỗi ngẫu nhiên × 600 nến, kể cả đoạn khởi tạo; test ghi cứng giá trị tham chiếu.

## 4. Đặc trưng

`regime`, `direction`, `ambiguous`, `adx14`, `plus_di`, `minus_di`, `atr14`, `vol_ratio`, `risk_off`, **theo dõi chuyển regime (REG-02):** phân loại lại 96 nến gần nhất **chỉ bằng dữ liệu tới từng nến** (không lưu trạng thái, tính lại được) → `bars_in_regime`, `regime_since`, `previous_regime`, `bars_in_regime_capped` (≥ 96 nến), `history` (12 nhãn gần nhất), driver `REGIME_CHANGED` khi nến cuối vừa đổi nhãn; `thresholds`; `coverage`.

**Trọng số gợi ý cho Fusion (REG-02):** chưa có cơ sở hiệu chỉnh → bảng **trung tính** (mọi analyst 1,0) ghi rõ `calibrated: false`, phiên bản `regime-weights-0-neutral`. GĐ4 / GĐ6 chốt bảng thật (đổi bảng → đổi phiên bản bảng + `VERSION`). Không bịa trọng số.

## 5. Chạy

Job `REGIME` (định tuyến có từ GĐ2: nến M15 vàng đóng, debounce) — mới có bộ xử lý; kết quả hết hạn (`as_of` + 15 phút + 2 phút) → `OUTPUT_EXPIRED` → tính lại (`RECOMPUTE`, `router-2026.11.14d`). `as_of` = giờ đóng nến cuối (như Technical) → cùng dữ liệu tính lại cùng `output_id`. Lưu `append_scoped` theo phạm vi nguồn giá. Đường lui `GT_ORCHESTRATOR=0` (vòng Technical cũ) **không** chạy Regime.

## 6. Kiểm chứng

29 test (tham chiếu ADX, ngưỡng, đi ngang / xu hướng lên / xuống / biến động cao + chuyển regime, mơ hồ, trọng số trung tính, thiếu lịch sử, trễ, đóng băng, độ phủ, spike, SAMPLE, 3-C06 thêm nến tương lai không đổi kết quả, đổi dữ liệu → id mới, router, bộ xử lý theo nguồn + idempotent). **Soát riêng (Postgres 16):** orchestrator thật, nạp từng nến 2 ngày (190 nến) → 190 kết quả, không trùng; tính lại tại đúng thời điểm → cùng `output_id` 190/190; **phân loại lại độc lập bằng `ta` + pandas** (ADX, ATR, trung vị trượt 960) → khớp 190/190 nhãn kể cả cờ mơ hồ (|ΔADX| ≤ 0,005 do làm tròn).

## 7. RISK_OFF từ proxy trú ẩn của Macro (`regime-1.1.0`, người dùng duyệt 2026-11-14)

- **Nguồn:** `flight_to_safety_proxy` của Macro (USD `z_1d ≥ 2` **và** lợi suất 10 năm `z_1d ≤ −2` — `30-macro-analyst.md`). Chỉ là **proxy** (thiếu cổ phiếu / VIX), chưa hiệu chỉnh.
- **Chọn kết quả Macro (point-in-time):** cùng **nguồn giá** (scope), `computed_at ≤ giờ đóng nến` (Macro tính sau lúc nến đóng không được dùng), còn hạn tại `as_of`. Thường là Macro của nến trước (trễ ≤ 1 nến). `output_id` Macro nằm trong băm đầu vào → tính lại cùng kết quả.
- **Kết quả:** proxy `true` → `regime = RISK_OFF` (ưu tiên cao nhất), cờ `RISK_OFF_REGIME`, driver `RISK_OFF_FLIGHT_TO_SAFETY_PROXY`; nhãn theo giá giữ ở `price_regime` (theo dõi chuyển regime vẫn tính trên `price_regime`). `false` → `risk_off = NO`. Macro thiếu / hết hạn / bị chặn / proxy không đánh giá được (thiếu USD hoặc lợi suất 10 năm chưa đủ lịch sử) → `risk_off = NOT_EVALUATED` + lý do (`MACRO_MISSING`, `MACRO_EXPIRED`, `MACRO_<trạng thái>`, `PROXY_UNAVAILABLE`), nhãn theo giá giữ nguyên.
- Trọng số Fusion cho `RISK_OFF`: vẫn trung tính (`calibrated: false`).
- **Kiểm chứng:** 6 test (YES / NO / không đánh giá; Macro thiếu / hết hạn / STALE; Macro tính sau nến đóng không dùng; Macro nguồn khác không dùng; idempotent). Soát Postgres: orchestrator thật Macro + Regime 60 nến có cú sốc USD + lợi suất → `RISK_OFF` 36 nến sau cú sốc, nến đầu `NOT_EVALUATED` (chưa có Macro tính trước); mọi Macro được dùng đều tính trước giờ đóng nến và còn hạn; tính lại cùng id 60/60.
