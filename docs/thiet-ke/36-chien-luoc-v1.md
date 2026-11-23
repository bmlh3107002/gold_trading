# 36 — Chiến lược v1 "Theo xu hướng M15" (STR-06) — ĐÃ DUYỆT 17/11

> 2026-11-17 · GĐ5 bước 7 · Q7 = (A): người phát triển soạn nháp từ luật GĐ4, **người dùng đọc, sửa, duyệt trước khi viết mã**.
> Mã chiến lược: `xu-huong-m15` · phiên bản **1.0.0** · trạng thái **CHƯA KIỂM CHỨNG** (DEC-25).

## 0. Đọc trước — chiến lược này là gì và không là gì

- Đây là **bộ luật viết sẵn**, không phải AI dự đoán. Nó chỉ làm theo "nhận định thị trường" (MarketView) mà hệ thống đã có từ GĐ4.
- **Chưa có bằng chứng nào cho thấy chiến lược này có lãi.** Mọi con số dưới đây là **giá trị khởi đầu chưa hiệu chỉnh**; GĐ6 (backtest) mới đo được. Đổi bất kỳ con số nào = phiên bản mới, cũng chưa kiểm chứng.
- Chỉ chạy **PAPER** (giả lập trong sổ cái). Hệ thống chặn cứng chiến lược chưa kiểm chứng ở SHADOW / LIVE. **Không có lệnh thật nào.**
- Chiến lược chỉ **đề nghị** (tạo "ý định giao dịch"). Risk Engine luôn có quyền từ chối hoặc giảm khối lượng. Chiến lược **không tự quyết số lot**.

## 1. Ý tưởng một câu

Khi giá vàng đang **có xu hướng rõ** (theo luật GĐ4) và giá **chưa chạy quá xa**, vào lệnh theo hướng xu hướng. Cắt lỗ cách 1,5 lần biên độ trung bình. Chốt lời gấp đôi khoảng cắt lỗ. Không giữ lệnh qua đêm.

## 2. Khi nào xét

Mỗi khi có **nhận định thị trường mới** (khoảng 15 phút một lần, sau khi nến M15 đóng), cho đúng nguồn giá của tài khoản. Không có nhận định còn hạn → không làm gì.

## 3. Điều kiện vào lệnh (phải đủ **tất cả**)

| # | Điều kiện | Vì sao |
| --- | --- | --- |
| V1 | Nhận định thị trường **còn hạn, chưa bị vô hiệu**, đúng nguồn giá của tài khoản | không dùng thông tin cũ |
| V2 | Hướng nghiêng là **LONG** (mua) hoặc **SHORT** (bán). `NEUTRAL` → không vào | GĐ4 chỉ cho hướng khi giá + regime đều cùng xu hướng |
| V3 | Điểm "chất lượng & đồng thuận" **≥ 0,6** | dưới 0,6 nghĩa là có nhóm phân tích phản đối hoặc dữ liệu kém |
| V4 | **Không** có cờ rủi ro nào sau: tin sắp ra / đang trong cửa sổ tin (`EVENT_SOON`, `EVENT_WINDOW`), sốc tin (`NEWS_SHOCK`), biến động cao (`HIGH_VOLATILITY`, `HIGH_VOLATILITY_REGIME`), thị trường né rủi ro (`RISK_OFF_REGIME`), căng thẳng vĩ mô (`MACRO_STRESS`), đám đông lệch một phía (`CROWDING_RISK`), spread giãn (`WIDE_SPREAD`), ngày lễ thanh khoản thấp (`LOW_LIQUIDITY_HOLIDAY`) | chỉ vào khi thị trường "bình thường" |
| V5 | Giờ New York từ **03:00 tới 12:00**, thứ Hai – thứ Năm; thứ Sáu chỉ tới **10:00** | phiên London + đầu phiên Mỹ, thanh khoản tốt; tránh bị buộc đóng cuối tuần ngay sau khi vào (H8). Giờ NY tự theo đổi giờ mùa hè / đông |
| V6 | Giá hiện tại cách đường trung bình EMA20 (M15) **không quá 1 ATR** | không "đuổi" giá đã chạy quá xa |
| V7 | **Không có lệnh nào đang mở** của chiến lược này trên tài khoản | v1 chỉ một lệnh một lúc (đơn giản, dễ kiểm) |
| V8 | Lệnh trước đã đóng ít nhất **30 phút** (2 nến M15) | tránh vào lại liên tục sau khi vừa bị cắt lỗ |

Ngoài ra Risk Engine vẫn tự kiểm mọi thứ của bước 1–6 (lỗ ngày / tuần / tháng, chuỗi thua, 4 lệnh / ngày, spread, ký quỹ, tin HIGH, cuối tuần…). Chiến lược **không** thay thế các kiểm tra đó.

## 4. Đặt lệnh

| Mục | Luật |
| --- | --- |
| Loại lệnh | Lệnh thị trường (khớp ngay), hiệu lực **60 giây** — quá 60 giây chưa duyệt / khớp thì bỏ |
| Cắt lỗ (SL) | Cách giá vào **1,5 × ATR14 (M15)** về phía ngược |
| Chốt lời (TP) | Cách giá vào **2 × khoảng SL** (tức 3 × ATR) về phía thuận |
| Mức rủi ro xin | Đúng mức trong hồ sơ rủi ro (0,25 %). Risk tính lot, gồm spread + trượt giá + phí |
| Chống trùng | Mỗi nhận định thị trường chỉ sinh **tối đa một** ý định; gửi lại cùng ý định thì Risk trả lại đúng quyết định cũ (bước 6) |

## 5. Quản lý lệnh đang mở

| Mục | Luật |
| --- | --- |
| Dời hòa vốn | Khi giá đi thuận **1 × khoảng SL** → dời SL tới **giá vào + chi phí** (spread, trượt giá, phí quy ra giá). Từ đó nếu giá quay lại chạm SL thì không lỗ sau chi phí; lệnh cũng thành "an toàn" để được giữ qua tin HIGH (H7) |
| Trailing (dời SL theo giá) | **Không có** ở v1 (ít tham số hơn, đỡ rủi ro "khớp quá mức" khi backtest) |
| Đóng theo giờ | Đóng mọi lệnh còn mở lúc **16:45 giờ New York** cùng ngày — **không giữ qua đêm** (không swap, tránh spread giãn lúc nghỉ 17:00) |
| Tín hiệu ngược chiều khi đang có lệnh (5-C03) | **Bỏ qua**: giữ lệnh cũ, để SL / TP / hòa vốn / đóng theo giờ xử lý. **Không** tự đảo lệnh, **không** mở lệnh ngược chiều |
| Cuối tuần / lễ, tin HIGH | Theo hồ sơ rủi ro (đã có ở bước 6): đóng hết 30 phút trước cuối tuần / lễ (H8); qua tin HIGH chỉ giữ lệnh đã dời hòa vốn (H7) |

## 6. Ví dụ bằng số (số **minh họa**, không phải số đo thật)

Giả sử: vốn 10.000 USD, rủi ro 0,25 % = **25 USD**; 1 lot = 100 oz; ATR14 M15 = 13 USD (con số ví dụ của bản đánh giá độc lập, chưa đo); spread 0,30; đệm trượt giá 0,40; phí 7 USD / lot.

- Nhận định: LONG, điểm 0,72, không cờ rủi ro, 09:15 NY thứ Ba. Giá bid 2.600,00 / ask 2.600,30. EMA20 = 2.595 → cách 5 USD ≤ 13 → được vào.
- SL = 2.600 − 1,5 × 13 = **2.580,50**; TP = 2.600 + 2 × 19,5 = **2.639,00**.
- Risk tính: rủi ro / lot = (19,5 + 0,30 + 0,40) × 100 + 7 = **2.027 USD** → 25 / 2.027 = 0,0123 → **0,01 lot**, rủi ro thật **20,27 USD** (≤ 25).
- R:R sau chi phí = ((39 − 0,30) × 100 − 7) / 2.027 = **1,91** ≥ 1,5 (H2) → được.
- Giá lên 2.619,50 (+1 × SL) → SL dời lên ≈ **2.601,17** (giá khớp 2.600,70 + đệm 0,40 + phí 0,07).
- Không chạm TP / SL tới 16:45 NY → đóng theo giá lúc đó.

**Lưu ý vốn:** với các số ví dụ trên, 0,01 lot (nhỏ nhất) đã có rủi ro ≈ 20,27 USD → cần vốn **≥ ≈ 8.100 USD** để nằm trong 0,25 %. Vốn nhỏ hơn → Risk **từ chối** mọi lệnh (không làm tròn lên). Số thật sẽ tính bằng ATR + spread thật trong báo cáo khả thi (bước 8, `cli kha-thi`).

## 7. Bảng tham số (để đếm và để GĐ6 đo — KN-07, KN-08)

| # | Tham số | Giá trị v1 | Nguồn |
| --- | --- | --- | --- |
| P1 | Điểm chất lượng tối thiểu | 0,6 | mốc "Cao" của giao diện GĐ4 |
| P2 | Danh sách cờ rủi ro cấm | mục 3 V4 | thận trọng: mọi cờ "bất thường" |
| P3 | Giờ vào lệnh (NY) | 03:00–12:00; thứ Sáu tới 10:00 | phiên London + đầu phiên Mỹ |
| P4 | Khoảng cách tối đa tới EMA20 | 1 ATR | không đuổi giá |
| P5 | Số lệnh mở cùng lúc | 1 | đơn giản |
| P6 | Nghỉ sau khi đóng lệnh | 30 phút | tránh vào lại liên tục |
| P7 | SL | 1,5 ATR | khoảng thường dùng 1–2 ATR |
| P8 | TP | 2 × SL | đạt R:R ≥ 1,5 sau chi phí (H2) |
| P9 | Dời hòa vốn khi lãi | 1 × SL | |
| P10 | Đóng theo giờ | 16:45 NY | không giữ qua đêm |
| P11 | Hạn của ý định | 60 giây | |

11 tham số, **tất cả chưa hiệu chỉnh**. GĐ6 chỉ được thử một số ít tham số đã đăng ký trước (giao thức KN-07, bước 9), không dò hết mọi tổ hợp.

## 8. Phiên bản + an toàn

- Mỗi ý định / quyết định ghi **phiên bản chiến lược**. Bản cũ giữ lại, quay lại được. Bản đã duyệt không tự chuyển sang bản mới.
- Chiến lược chỉ đọc dữ liệu; **không có đường nào tới Gateway / MT5 để gửi lệnh** (sẽ có test khẳng định).
- Dữ liệu mẫu (`SAMPLE`) → ý định vẫn mang nhãn mẫu, không bao giờ đi tới quyết định thật.
- Thiếu dữ liệu (không có ATR, EMA20, giá mới) → **không vào lệnh**, ghi lý do. Không đoán.

## 9. Sẽ làm gì sau khi người dùng duyệt (bước 7, chưa làm)

1. STR-02/03: mã `strategy/` sinh ý định theo mục 3–4 (đọc MarketView + Technical của đúng nhận định đó).
2. STR-04 / 5-C04: một ý định / nhận định, một lệnh mở, nghỉ 30 phút.
3. Quản lý lệnh mục 5 (dời hòa vốn, đóng 16:45 NY) + nối nhịp `PaperMonitor.tick` (bước 6).
4. STR-05: lưu ý định + quyết định Risk + lý do; nối sau Fusion trong nhịp orchestrator → Risk → sổ cái paper.
5. Soát riêng: chạy trên nến mẫu nhiều ngày qua orchestrator thật.

## 10. Nhật ký

- **2026-11-17** — Bản nháp 1.0.0 (người phát triển soạn từ luật GĐ4).
- **2026-11-17** — **Người dùng duyệt cả bản 1.0.0** (chọn "Duyệt cả bản", không sửa điểm nào). Vẫn **chưa kiểm chứng** (DEC-25): chỉ PAPER tới khi backtest GĐ6 + người dùng duyệt lại.

## 11. Hiện thực (17/11)

| Phần | Mã | Ghi chú |
| --- | --- | --- |
| Luật vào + đặt lệnh (mục 3–4) | `strategy/trend_m15.py` `decide`, `Params` (P1–P11) | hàm thuần; thiếu dữ liệu → bỏ qua có mã (`MISSING_*`); giá tham chiếu = bid; SL làm tròn ra xa, TP vào gần theo point; khóa idempotency = băm(chiến lược@phiên bản, nguồn giá, MarketView) |
| Quản lý lệnh (mục 5) | `strategy/trend_m15.py` `Manager`, `time_stop_at` | qua `PaperMonitor.tick`: hòa vốn = giá khớp + đệm trượt giá + phí / cỡ HĐ (rủi ro còn lại = 0), một lần; `TIME_STOP` 16:45 NY |
| Nối luồng (mục 9) | `strategy/runner.py` `StrategyRunner`, `api/app.py` | mỗi nhịp orchestrator sau Fusion; quản lý lệnh ở mọi chế độ, ý định mới chỉ ở PAPER; nhật ký `strategy_evaluations` (migration 0027); tắt bằng `GT_PAPER_STRATEGY=0` |

Giữ chỗ còn mở (đã duyệt, chưa khớp) cũng tính là "đang có lệnh" (V7). Lệnh không mang mã chiến lược này → `Manager` không đụng tới.

- **2026-11-23 (GĐ6, nhánh `gd6-backtest`)** — `StrategyRunner` tạo ý định ở `PAPER` **hoặc** `BACKTEST` (MOD-03; chỉ tài khoản mô phỏng của backtest có chế độ này). Luật chiến lược không đổi, phiên bản giữ `1.0.0`.
