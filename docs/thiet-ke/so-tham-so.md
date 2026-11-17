# Sổ tham số (KN-08) — mọi con số chưa hiệu chỉnh, GĐ2–GĐ5

> 2026-11-17 · GĐ5 bước 9 · **người dùng duyệt 17/11** (cùng giao thức đánh giá [`38-giao-thuc-danh-gia.md`](38-giao-thuc-danh-gia.md)).
>
> Mục đích: biết rõ hệ thống có **bao nhiêu "nút vặn"** trước khi backtest. Mỗi nút được vặn thêm ở GĐ6 làm tăng nguy cơ "backtest đẹp do khớp quá mức" (Bailey và cộng sự, 2017). Vì vậy GĐ6 **chỉ được thử các nút loại A**, với lưới giá trị ghi sẵn ở giao thức; mọi nút khác giữ nguyên.

## Loại

| Loại | Nghĩa | GĐ6 được thử? |
| --- | --- | --- |
| **A** | Tham số của chiến lược, ảnh hưởng trực tiếp tới lãi lỗ | **Có — chỉ 3 nút** trong giao thức (P1, P7, P8), lưới cố định |
| **B** | Ngưỡng mô tả / chất lượng dữ liệu của analyst, Fusion (luật GĐ3–GĐ4) | Không. Chỉ **đo** (báo cáo) — đổi = phiên bản analyst mới, cần quyết định riêng |
| **S** | Ngưỡng an toàn (chặn khi nghi ngờ) | Không bao giờ nới để "đẹp" kết quả. Chỉ siết thêm, hoặc đổi khi có số đo thật cho thấy chặn nhầm quá nhiều — người dùng duyệt |
| **U** | Số **người dùng chọn** (hồ sơ rủi ro H1–H11, chính sách) | Không. GĐ6 chạy đúng số người dùng đã chốt |
| **K** | Hằng kỹ thuật (độ tươi dữ liệu, hạn sử dụng) | Không |

Đổi bất kỳ số nào → **tăng phiên bản** của thành phần đó (vd. `technical-1.6.0` → `1.7.0`) + ghi vào bảng này + ghi file giai đoạn. Kết quả mới gắn phiên bản mới.

## 1. Chiến lược v1 `xu-huong-m15@1.0.0` (thiết kế 36 mục 7)

| Mã | Giá trị | Loại | Lý do chọn ban đầu |
| --- | --- | --- | --- |
| P1 điểm chất lượng tối thiểu | 0,6 | **A** | mốc "Cao" của giao diện GĐ4 |
| P2 danh sách cờ rủi ro cấm (10 cờ) | thiết kế 36 V4 | S | chỉ vào khi thị trường "bình thường" |
| P3 giờ vào lệnh New York | 03:00–12:00, thứ Sáu tới 10:00 | B | phiên London + đầu phiên Mỹ |
| P4 cách EMA20 tối đa | 1 ATR | B | không đuổi giá |
| P5 số lệnh mở cùng lúc | 1 | S | đơn giản, dễ kiểm |
| P6 nghỉ sau khi đóng | 30 phút | B | tránh vào lại liên tục |
| P7 cắt lỗ | 1,5 ATR | **A** | khoảng thường dùng 1–2 ATR |
| P8 chốt lời | 2 × khoảng SL | **A** | để R:R sau chi phí ≥ 1,5 (H2) |
| P9 dời hòa vốn | khi lãi 1 × SL | B | |
| P10 đóng theo giờ | 16:45 New York | S | không giữ qua đêm |
| P11 hạn ý định | 60 giây | K | |

## 2. Risk Engine + sổ cái paper (thiết kế 35)

| Mã | Giá trị | Loại | Lý do |
| --- | --- | --- | --- |
| `EQUITY_MAX_AGE` | 30 giây | K | = hạn nhịp tim Gateway |
| `QUOTE_MAX_AGE` | 10 giây | K | = ngân sách độ trễ làn nhanh |
| Cửa sổ nền spread | 30 ngày | B | Q4 / Q5 người dùng chốt |
| Số phút nền tối thiểu | 6.900 | S | ≈ 5 ngày giao dịch; ít hơn → từ chối |
| Đệm trượt giá + ngưỡng spread quá rộng | p95 spread 30 ngày | S | **proxy**, không phải trượt giá đo được — đo lại bằng deal thật ở GĐ9 |
| Hạn quyết định Risk | 30 giây | K | |
| Swap tính trước | 1 đêm (×3 thứ Tư) | S | chiến lược đóng trong ngày; vẫn trừ để an toàn |
| Giá đóng khi chạm SL (paper) | `min(SL, bid)` (BUY) | S | khoảng trống giá cho giá xấu hơn |
| TP (paper) | đúng TP, không trượt có lợi | S | |
| Cùng giây chạm SL và TP | coi là SL | S | |
| Quét lại giây giá đến muộn | lùi 60 giây; từ lúc mở mỗi 5 phút | K | |
| Equity `cli kha-thi` | bản ghi theo giờ ≤ 2 giờ | K | |

## 3. Hồ sơ rủi ro người dùng (H1–H11, chốt 16/11) — loại **U**, GĐ6 không đổi

Rủi ro / lệnh 0,25 %; R:R ≥ 1,5; tổng rủi ro mở 0,5 %; lỗ ngày / tuần / tháng 0,75 / 1,5 / 3 %; 5 lệnh thua liên tiếp → tạm dừng; 4 lệnh / ngày; mốc ngày 17:00 New York; dừng hẳn khi sụt 5 % từ đỉnh; qua tin HIGH chỉ giữ lệnh an toàn; đóng hết 30 phút trước cuối tuần / lễ; đòn bẩy thực tế ≤ 3; nạp / rút tách riêng; chỉ thêm lệnh cùng chiều khi mọi lệnh đang lời. Giới hạn DEC-09 (0,25–0,5 %) là luật cứng.

## 4. Fusion + Quality Gate (thiết kế 33) — `fusion-rules-1.0.0`, `quality-policy-1`

| Mã | Giá trị | Loại |
| --- | --- | --- |
| Hệ số khi thiếu nhóm tùy chọn | × 0,9 | B |
| Hệ số khi 1 nhóm phản đối | × 0,5 | B |
| Số nhóm phản đối → NEUTRAL | ≥ 2 | B |
| Trần hạn MarketView | 30 phút | K |
| Mốc hiển thị Cao / Trung bình | 0,6 / 0,3 | B (P1 dùng lại 0,6) |

## 5. Analyst (GĐ3)

| Thành phần | Con số | Loại |
| --- | --- | --- |
| Technical (`technical-1.6.0`) cổng chất lượng | ≥ 250 nến; phủ ≥ 99 %; trễ ≤ 2 phút; 4 nến giống hệt = đóng băng; nến > 8 × trung vị biên độ = spike (confidence × 0,5); spread > 3 × trung vị | S |
| Technical đặc trưng | ATR14 Wilder; EMA20 / EMA50; dốc EMA50 > 0,1 ATR / 10 nến; `vol_ratio` > 2 = biến động cao (nền 96 nến); fractal k = 3; vùng giá 0,5 / 1 ATR, ≥ 2 lần chạm; EWMA λ = 0,94; hạn 15 + 2 phút | B |
| Mẫu hình nến (TEC-06) | ngưỡng sách vở, chỉ mô tả | B |
| Regime (`regime-1.2.0`) | ADX ≥ 25 TREND, ≤ 20 RANGE, vùng mơ hồ 20–25 (cắt 22,5); `vol_ratio` ≥ 2 (nền 960 nến) = HIGH_VOL, mơ hồ [1,8; 2,2); lịch sử 96 nến; trần confidence mơ hồ 0,5 | B |
| Event (`event-1.0.0`) | `SOON` 60 phút; trần 0,5 khi lịch mâu thuẫn; hạn 15 / 2 phút | B |
| Cửa sổ tin (thiết kế 17) | HIGH −15 / +15 phút; MEDIUM −5 / +10; LOW 0 / +5; chưa chắc giờ → cả ngày | S |
| Macro (`macro-1.1.0`) | hướng `|z_5d|` ≥ 1; `MACRO_STRESS` `|z_1d|` ≥ 3; chạy về an toàn USD z ≥ 2 và lợi suất z ≤ −2; 60 quan sát / 20 ngày | B |
| Positioning (`positioning-1.0.0`) | ≥ 52 tuần, tối đa 156; `|z|` ≥ 2 = đám đông lệch; báo cáo > 14 ngày = cũ | B |
| News (`news-1.1.0`) | chiều tác động theo lý thuyết; LLM mặc định tắt; tin trái chiều → trần 0,5 | B |

## 6. Làn nhanh + dữ liệu (GĐ1–GĐ2, DEC-20)

| Con số | Giá trị | Loại |
| --- | --- | --- |
| Chặn sau số liệu HIGH | 15 phút thị trường mở từ lúc biết số | S |
| Spread giãn | > 3 × trung vị 60 phút | S |
| Ngân sách độ trễ làn nhanh | 10 giây | S |
| Thông cáo Fed "cũ" | > 36 giờ | K |
| Giây giá spread giãn (ING-08) | > 3 × trung vị 1 giờ, cần ≥ 60 mẫu | S |
| CSV sai múi giờ (R1) | > 1 % nến rơi vào giờ đóng cửa → từ chối file | S |

## 7. Đếm

- Loại **A** (được thử ở GĐ6): **3** — P1, P7, P8.
- Mọi con số khác: giữ nguyên trong backtest; GĐ6 **báo cáo** ảnh hưởng của chúng (vd. tỷ lệ MarketView NEUTRAL, tỷ lệ bị chặn vì tin) nhưng không dò.
- Mỗi lần thử ngoài kế hoạch phải **cộng vào số lần thử** dùng cho Deflated Sharpe (giao thức mục 6) và ghi lại ở đây.

## Nhật ký

- **2026-11-17** — Bản nháp đầu (người phát triển gom từ thiết kế 03, 17, 26, 28–33, 35–37). Chờ người dùng duyệt.

- **2026-11-17** — Người dùng duyệt cả bản. GĐ6 chỉ thử P1, P7, P8 theo lưới của giao thức `protocol-1`.
