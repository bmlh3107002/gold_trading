# 31 — Analyst Positioning / COT (GĐ3 bước 5 — POSN-01, POSN-02)

> Tạo 2026-11-14. Kế hoạch: `docs/ke-hoach/GD3-ke-hoach.md` bước 5. Code: `backend/src/gold_trading/analysts/positioning.py`. Test: `tests/test_positioning.py`. Dữ liệu GĐ1: `20-cot-vang.md` (`cftc_cot_gold`). Đặc tả: `04-cac-analyst.md` mục 5.

## 1. Vai trò

Mô tả **vị thế của quỹ / đầu cơ** (nhóm không thương mại, báo cáo legacy futures only, GOLD 088691) và mức **đông đúc** so với lịch sử — bối cảnh **nhiều tuần**. Không tín hiệu, không xác suất. Phạm vi **toàn cục** (`GLOBAL_SCOPE`).

## 2. Đầu vào + độ trễ

- Báo cáo COT point-in-time: chỉ thấy từ **giờ công bố chính thức** (thứ Sáu 15:30 New York; lễ dời) — `available_at` của GĐ1. Có test: nạp trước giờ công bố vẫn không thấy.
- **Luôn trễ**: `data_lag_days` (từ ngày chốt thứ Ba) + cờ `COT_LAGGED` trên mọi kết quả; thẻ web luôn ghi "trễ N ngày, không phải dữ liệu thời gian thực".
- Báo cáo dùng được mới nhất cũ > **14 ngày** (như `data_ttl` nguồn) → `STALE` (chặn). Báo cáo hỏng (OI ≤ 0 / thiếu số) → bỏ qua + cờ `COT_REPORT_UNUSABLE_SKIPPED`; **không** dùng 0, và nếu bỏ nó làm số còn lại quá cũ → STALE.
- ETF, ngân hàng trung ương: chưa có nguồn (quyết ở Gate GĐ1) → `OPTIONAL_MISSING:etf_flows` / `central_banks`, ghi `NOT_AVAILABLE`.

## 3. Tính toán

- `net_pct_oi = ròng không thương mại / khối lượng mở` (chuẩn hóa theo quy mô thị trường).
- Cực trị (POSN-01): **cần ≥ 52 tuần**, đọc tối đa 156 tuần (3 năm). `z` = (hiện tại − trung bình) / độ lệch chuẩn tổng thể; `percentile` = tỉ lệ tuần ≤ hiện tại. Thiếu lịch sử → `crowding = INSUFFICIENT_DATA`, cờ `COT_HISTORY_SHORT`, trần confidence 0,5.
- POSN-02: `|z| ≥ 2` → `CROWDED_LONG` / `CROWDED_SHORT`, cờ `CROWDING_RISK`, **giả thuyết contrarian** (`CONTRARIAN_DOWNSIDE_RISK` / `UPSIDE_RISK`) ghi rõ "chưa kiểm chứng". σ = 0 → `COT_ZERO_DISPERSION`, không z.
- Ngưỡng 52 / 156 tuần, |z| 2: giá trị khởi đầu **chưa hiệu chỉnh**. Đổi → tăng `VERSION` (`positioning-1.0.0`).

> **Ghi nhận thực tế:** GĐ1 chỉ nạp báo cáo **mới nhất** (từ ~11/2026; báo cáo cũ hơn bị từ chối có chủ ý) → cần **~1 năm** mới đủ 52 tuần. Tới lúc đó chỉ có vị thế ròng + thay đổi tuần, `crowding = INSUFFICIENT_DATA`. Muốn có ngay: nạp bù lịch sử từ file năm của CFTC (`cftc.gov/files/dea/history/…`, cùng báo cáo legacy) — việc của GĐ1, cần người dùng quyết; máy chủ đám mây bị cftc.gov chặn → phải tải từ máy người dùng.

## 4. Chạy

Job `POSITIONING` (định tuyến GĐ2: báo cáo COT mới / sửa) có bộ xử lý; hết hạn → tính lại (`router-2026.11.14f`); dự phòng mỗi nhịp. `as_of = max(now − 5 giây, lúc biết)`; đã có kết quả còn hạn tính sau lúc biết → bỏ qua. Hết hạn: 6 giờ, hoặc lúc báo cáo thành cũ (> 14 ngày) nếu sớm hơn; bị chặn: 15 phút. API `GET /api/analysts/positioning/latest` (đăng nhập, dữ liệu chung); thẻ "Vị thế quỹ đầu cơ (COT)" trang Thị trường, có dòng ghi nguồn CFTC.

## 5. Kiểm chứng

23 test: báo cáo thật 03/11/2026 (số tay của GĐ1), không thấy trước giờ công bố, tham chiếu tay (26 tuần 20 % + 26 tuần 40 % → z = 1, thứ hạng 1,0), đông phía mua / bán + giả thuyết, giới hạn 156 tuần, σ = 0, thiếu / cũ, báo cáo hỏng bị bỏ (không thành 0), bản sửa biết sau không viết lại quá khứ, router, bộ xử lý, API (401 khi chưa đăng nhập). **Soát riêng (Postgres 16):** 200 tuần ngẫu nhiên, orchestrator thật 12 báo cáo → 12 kết quả không trùng, mỗi báo cáo có kết quả ngay; pandas tính lại z / thứ hạng / % độc lập → khớp.
