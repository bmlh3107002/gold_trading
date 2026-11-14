# 30 — Analyst Macro bằng luật (GĐ3 bước 4 — MAC-01, MAC-02)

> Tạo 2026-11-14. Kế hoạch: `docs/ke-hoach/GD3-ke-hoach.md` bước 4. Code: `backend/src/gold_trading/analysts/macro.py`. Test: `tests/test_macro.py`. Khung chung: `27-khung-analyst.md`. Đặc tả: `docs/huong-dan-chuc-nang/04-cac-analyst.md` mục 4. Dữ liệu GĐ1: H.15 (`18-h15-lai-suat.md`), chỉ số USD tự tính (`19-chi-so-usd.md`), proxy Fed (DEC-04).

## 1. Vai trò + phạm vi

Mô tả **bối cảnh vĩ mô** của vàng: lợi suất thực, USD, lãi suất danh nghĩa, kỳ vọng Fed — mức, thay đổi, độ bất thường, hướng — và một `macro_bias` theo luật. Không dự báo, không xác suất.

**Theo nguồn giá vàng của tài khoản** (phạm vi như Technical / Regime): chỉ số USD tính trên giá **broker của tài khoản** (DEC-14, không trộn broker); H.15 dùng chung. Nguồn không phải MT5 (SAMPLE / CSV) → không có chỉ số USD.

## 2. Đầu vào (khung chung)

| Đầu vào | Bắt buộc | Thiếu / hỏng |
| --- | --- | --- |
| Lợi suất thực 10 năm (`UST_TIPS_10Y`, H.15) | **có** | Không có → `MISSING`; quan sát mới nhất cũ > 7 ngày → `STALE`; < 6 quan sát → `INVALID` (`INSUFFICIENT_HISTORY`) |
| Lợi suất danh nghĩa 10 / 2 năm (H.15) | không | cờ `OPTIONAL_*` |
| Chỉ số USD tự tính (6 cặp, broker) | không | Analyst **vẫn chạy**; cờ `USD_INDEX_UNAVAILABLE` + trần confidence 0,5. Lý do: broker / Gateway chưa gửi đủ 6 cặp không được làm tê liệt cả analyst. Giá vô lý / mơ hồ symbol → cờ `OPTIONAL_<lý do>:usd_index` |
| Proxy kỳ vọng Fed (`macro_view`, DEC-04) | — | Chỉ mô tả (lean, chênh lệch đcb), `INSUFFICIENT_DATA` nếu thiếu |

Ô "n.a." của H.15 không bao giờ thành 0 (bỏ qua). Point-in-time: bản ghi biết sau `as_of` (kể cả **bản sửa** H.15) không đổi kết quả cũ — có test.

## 3. Tính toán

**Lãi suất (H.15):** tối đa 61 quan sát gần nhất; thay đổi 1 / 5 kỳ theo **điểm cơ bản** bằng `Decimal` (chuỗi gốc H.15); độ lệch chuẩn (tổng thể) của thay đổi ngày; `z_1d = Δ1 / σ`, `z_5d = Δ5 / (σ·√5)`. **Cần ≥ 21 quan sát** (20 thay đổi) mới tính z; ít hơn → vẫn có mức + thay đổi, `z` / hướng = `null`, cờ `Z_HISTORY_SHORT:<chuỗi>` (+ trần 0,5 nếu là lợi suất thực).

> **Ghi nhận thực tế:** trang H.15 chỉ hiện ~5 ngày gần nhất; máy người dùng nạp từ ~12/11/2026 → khoảng giữa tháng 12 mới đủ 21 quan sát. Tới lúc đó `macro_bias` = `INSUFFICIENT_DATA` (đúng hướng an toàn). Muốn có ngay: nạp bù lịch sử H.15 từ Data Download Program của Fed — việc của GĐ1 (nguồn mới), cần người dùng quyết.

**Chỉ số USD:** dùng đúng `usd_index` (GĐ1) cho giá trị hiện tại + trạng thái; chuỗi lịch sử trên **các nến M15 chung của 6 cặp** (bỏ nến có giá vô lý), tối đa 20 ngày (1.920 lợi suất log). `Δ1` / `Δ5` = log(I_t / I_{t−96}) / log(I_t / I_{t−480}); σ = độ lệch chuẩn lợi suất log M15 20 ngày; `z_1d = Δ1 / (σ·√96)`, `z_5d = Δ5 / (σ·√480)`. Cần ≥ 481 điểm.

**Hướng:** `|z_5d| ≥ 1` → `UP` / `DOWN`, ngược lại `FLAT`.

**`macro_bias`** (vàng **ngược chiều lý thuyết** với USD và lợi suất thực — chưa hiệu chỉnh): mỗi yếu tố đi xuống → hỗ trợ, đi lên → cản; `SUPPORTIVE` (chỉ có hỗ trợ), `HEADWIND` (chỉ có cản), `MIXED` (cả hai — **3-C08**: driver `MACRO_DRIVERS_CONFLICT` + trần 0,5), `NEUTRAL` (đều đi ngang), `INSUFFICIENT_DATA` (không yếu tố nào có hướng). `bias_complete` = cả hai yếu tố đều có hướng.

**Cờ rủi ro:** `MACRO_STRESS` khi `|z_1d| ≥ 3` ở lợi suất thực / danh nghĩa 10 năm / USD; `FLIGHT_TO_SAFETY_PROXY` khi USD `z_1d ≥ 2` **và** lợi suất 10 năm `z_1d ≤ −2` (proxy "chạy về tài sản an toàn" — chỉ mô tả; **chưa** dùng làm `RISK_OFF` cho Regime: cần người dùng duyệt).

Ngưỡng 1 / 3 / 2, cửa sổ 60 quan sát / 20 ngày: giá trị khởi đầu **chưa hiệu chỉnh** — xem lại ở GĐ6. Đổi số nào → tăng `VERSION` (`macro-1.0.0`).

## 4. Chạy

Job `MACRO` (định tuyến GĐ2: nến M15 cặp tiền — debounce, số vĩ mô mới) có bộ xử lý: nến cặp tiền → các nguồn vàng **cùng server**; số H.15 mới → mọi nguồn vàng đang dùng; hết hạn (`as_of` + 17 phút) → tính lại (`router-2026.11.14e`). `as_of = max(now − 5 giây, lúc biết sự kiện)`; đã có kết quả còn hạn tính sau lúc biết → bỏ qua (6 cặp cùng một nến → một kết quả). Dự phòng mỗi nhịp: nguồn vàng chưa có kết quả còn hạn quá 60 giây → tính ngay.

## 5. Kiểm chứng

23 test: giá trị tham chiếu tay (thay đổi ±2 đcb xen kẽ → σ = 2, z1 = 1, z5 = 0,4472; USDJPY ×/÷1,001 xen kẽ → thay đổi 0, z 0, khớp `usd_index`), bảng luật bias, USD tăng mạnh → `UP`, thiếu USD / không server / lịch sử USD ngắn, bias hỗ trợ, mâu thuẫn, stress, thiếu / cũ / thiếu lịch sử lợi suất thực, tuần đầu chỉ có mức (không z), bản sửa biết sau không viết lại quá khứ, router, chọn nguồn vàng theo server + bỏ qua trùng + dự phòng. **Soát riêng (Postgres 16):** orchestrator thật, 6 cặp ngẫu nhiên 2.600 nến + 80 ngày H.15, nạp từng nến 1 ngày → 97 kết quả không trùng, tính lại tại đúng thời điểm cùng `output_id` 97/97; **tính lại độc lập bằng pandas** (chỉ số USD, Δ, z; 3 chuỗi lãi suất Δ, z) → lệch 0.
