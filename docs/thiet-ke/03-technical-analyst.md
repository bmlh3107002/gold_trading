# Thiết kế chi tiết — Technical analyst v1 (bước ③)

> Phiên bản thuật toán: `technical-1.0.0`. Mọi thay đổi công thức hoặc ngưỡng phải tăng phiên bản và ghi lý do tại đây.

## 1. Phạm vi — analyst này KHÔNG làm gì

- **Không dự báo xác suất tăng/giảm.** `docs/04` có nhắc LightGBM ước lượng `pUp/pDown`, nhưng con số xác suất chỉ có nghĩa sau khi train và hiệu chỉnh trên **dữ liệu thật**. v1 chỉ mô tả **trạng thái hiện tại** của giá bằng quy tắc xác định (deterministic).
- **Không ra tín hiệu mua/bán.** Đầu ra là đặc trưng (features) cho Fusion và Strategy dùng sau.
- `confidence` của v1 **chỉ đo chất lượng dữ liệu đầu vào** (độ phủ, spike, feed đóng băng, dữ liệu mẫu), **không đo khả năng dự báo đúng**. Giao diện phải ghi rõ điều này.

## 2. Đầu vào

- Nến XAUUSD M15 **đã đóng**, đọc point-in-time tại `as_of` (`store.query(..., as_of)`), từ **một nguồn duy nhất** (`GT_DATA_SOURCE`).
- Cửa sổ: **300 nến** gần nhất (≈ 3 ngày giao dịch). Lấy thêm **200 nến warm-up** cho EMA/ATR (đã kiểm chứng: lệch 0 so với tính trên toàn bộ lịch sử).

## 3. Cổng chất lượng dữ liệu (R1–R6)

Chạy trước mọi phép tính. Không đạt cổng **bắt buộc** thì **không xuất đặc trưng**, chỉ trả `source_status` lỗi kèm lý do.

| Mã | Kiểm tra | Ngưỡng | Không đạt thì |
| --- | --- | --- | --- |
| R6 `INSUFFICIENT_HISTORY` | Số nến trong cửa sổ | < 250 | **Bắt buộc**: không xuất |
| R2 `LOW_COVERAGE` | Số nến có / số nến lẽ ra có trong giờ mở cửa (300 nến gần nhất) | < 99% | **Bắt buộc**: không xuất |
| — `STALE_INPUT` | Nến cuối = nến lẽ ra đã đóng gần nhất (trễ tối đa 2 phút) | sai | **Bắt buộc**: `source_status=STALE` |
| R4 `FROZEN_FEED` | ≥ 4 nến liên tiếp có OHLC giống hệt nhau | có | **Bắt buộc**: `source_status=STALE` |
| R3 `SPIKE_IN_WINDOW` | Biên độ nến, hoặc khoảng nhảy so với close trước, > 8 × trung vị biên độ của cửa sổ | có | Xuất, nhưng confidence × 0,5 |
| R5 `WIDE_SPREAD` | Spread nến cuối > 3 × trung vị spread của cửa sổ | có | Xuất, gắn cờ rủi ro `WIDE_SPREAD` |
| — `SAMPLE_DATA` | Nguồn là `SAMPLE` | có | Xuất, gắn cờ; **cấm dùng cho SHADOW/LIVE** |

R1 (tự kiểm tra múi giờ khi nạp CSV) nằm ở bước nạp dữ liệu: nếu > 1% nến rơi vào giờ đóng cửa thì **từ chối cả file** và gợi ý múi giờ khớp nhất.

**Lý do chọn ngưỡng:** 99% cho phép lỡ khoảng 3 nến trong 300 (lỗi nhỏ của feed) nhưng chặn trường hợp thiếu cả buổi. 8 × trung vị: vàng M15 hiếm khi có nến lớn hơn 4–5 lần trung vị, kể cả lúc ra tin. Đặt 8 để chỉ bắt lỗi feed, không bắt biến động tin thật (tin thật do Event analyst xử lý). Các ngưỡng này **phải được kiểm tra lại trên dữ liệu thật của broker**.

## 4. Đặc trưng (features)

| Đặc trưng | Công thức |
| --- | --- |
| `atr14` | ATR Wilder: TR = max(H−L, \|H−C₋₁\|, \|L−C₋₁\|); ATR đầu = SMA(TR, 14), sau đó ATR = (ATR₋₁ × 13 + TR) / 14 |
| `atr_pct` | atr14 / close |
| `vol_ratio` | atr14 / trung vị(atr14 của 96 nến gần nhất ≈ 1 ngày). > 2 thì gắn cờ rủi ro `HIGH_VOLATILITY` |
| `ema20`, `ema50` | EMA khởi tạo bằng SMA (`analysts/indicators.py`) |
| `ema50_slope_atr` | (ema50 − ema50 của 10 nến trước) / atr14 |
| `trend` | `UP` nếu ema20 > ema50 **và** close > ema50 **và** slope > +0,1; `DOWN` nếu ngược lại cả ba; còn lại `FLAT` |
| `trend_strength_atr` | (ema20 − ema50) / atr14 |
| `rsi14` | RSI Wilder |
| `swings` | Fractal k = 3: nến *i* là swing high nếu high[i] > high của 3 nến mỗi bên. **Chỉ được xác nhận khi đã đóng đủ 3 nến sau** (không nhìn trước) |
| `structure` | Hai swing high và hai swing low gần nhất: HH+HL = `BULLISH`, LH+LL = `BEARISH`, còn lại `MIXED` |
| `levels` | Gom các swing đã xác nhận trong cửa sổ thành vùng giá, dung sai 0,5 × atr14; mỗi vùng có số lần chạm. Giữ các vùng chạm ≥ 2 lần |
| `nearest_support` / `nearest_resistance` | Vùng gần nhất dưới / trên close, kèm khoảng cách tính theo ATR |

## 5. Đầu ra (`AnalystOutput`)

- `analyst_id = "technical"`, `version = "technical-1.0.0"`.
- `as_of` = `close_time` của nến cuối; `expires_at` = `as_of` + 15 phút + 2 phút. Quá hạn thì Fusion không được dùng.
- `features`: các đặc trưng ở mục 4, cộng `input`: nguồn, số nến, nến đầu/cuối, revision lớn nhất, **hash đầu vào** (SHA-256 của OHLC theo thứ tự), dùng để tái lập kết quả.
- `quality_flags`, `risk_flags`, `source_status`, `confidence` (chỉ chất lượng dữ liệu).
- Lưu vào bảng append-only `analyst_outputs`, khóa duy nhất `(analyst_id, version, symbol, timeframe, source, as_of, input_hash)`. Chạy lại cùng đầu vào thì **không ghi trùng**.

## 6. Kiểm thử bắt buộc

- ATR Wilder so với giá trị tính tay.
- Swing không nhìn trước: kết quả tại `as_of` không đổi khi thêm nến sau `as_of`.
- Từng cổng R2–R6 với dữ liệu xấu cố ý.
- Cùng đầu vào thì cùng đầu ra và cùng hash. Đổi một giá thì hash đổi.

## 7. Kết quả kiểm chứng (2026-11-05)

- **Đối chiếu với thư viện độc lập `ta` 0.11.0**, trên 7.916 nến, bỏ 300 nến đầu để hai bên hội tụ: ATR14 lệch tối đa 5×10⁻¹¹; RSI14 lệch 5×10⁻⁹; EMA50 lệch 1×10⁻⁴ trên giá ~2.500 (thư viện kia khởi tạo EMA bằng giá đầu tiên thay vì SMA nên hội tụ chậm hơn).
- **Quy ước khởi tạo ATR:** theo TA-Lib, giá trị đầu tại chỉ số 14 = SMA(TR[1..14]). TR[0] bị bỏ vì chưa có close trước. Một số thư viện tính cả TR[0] nên giá trị *đầu tiên* khác, nhưng nằm trong đoạn warm-up nên không ảnh hưởng kết quả.
- **Tái lập và không nhìn trước:** mô phỏng chạy realtime 40 nến, sau đó thêm 20 nến "tương lai" rồi tính lại từng kết quả tại đúng thời điểm cũ: lệch 0/40.
- **Docker + PostgreSQL:** migration 0003 chạy, kết quả được lưu, restart không ghi trùng, DELETE trên `analyst_outputs` bị chặn.

## 8. Giới hạn đã biết

- **Ngày lễ:** lịch thị trường chưa có ngày lễ, nên quanh Giáng sinh/năm mới độ phủ có thể dưới 99% và analyst sẽ **tự chặn** (an toàn nhưng gây gián đoạn) trong tối đa ~3 ngày, cho tới khi có lịch giao dịch thật từ MT5 (R12).
- Ngưỡng R2–R6 mới được kiểm tra trên dữ liệu mẫu; **phải kiểm tra lại trên CSV thật của broker**.
- Không có xác suất và không có tín hiệu. Fusion/Strategy không được coi `trend` là lệnh mua/bán khi chưa có backtest.
