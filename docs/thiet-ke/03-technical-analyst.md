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

| — `CALENDAR_MISMATCH` | Có nến thật vào lúc lịch nói là đóng cửa | có | **Bắt buộc**: không xuất (lịch broker hoặc múi giờ khai báo sai) |

R1 (tự kiểm tra múi giờ khi nạp CSV) nằm ở bước nạp dữ liệu: nếu > 1% nến rơi vào giờ đóng cửa thì **từ chối cả file** và gợi ý múi giờ khớp nhất.

**Lý do chọn ngưỡng:** 99% cho phép lỡ khoảng 3 nến trong 300 (lỗi nhỏ của feed) nhưng chặn trường hợp thiếu cả buổi. 8 × trung vị: vàng M15 hiếm khi có nến lớn hơn 4–5 lần trung vị, kể cả lúc ra tin. Đặt 8 để chỉ bắt lỗi feed, không bắt biến động tin thật (tin thật do Event analyst xử lý). Các ngưỡng này **phải được kiểm tra lại trên dữ liệu thật của broker**.

### Lịch giao dịch dùng cho R2 và độ mới dữ liệu (từ `technical-1.1.0`)

"Nến lẽ ra phải có" = lịch tham chiếu (NY 18:00 CN → 17:00 T6, nghỉ 17:00–18:00) **giao** với giờ báo giá chính thức của broker, nếu đã khai báo:

- `GT_BROKER_SESSIONS`: chép từ MT5 → Market Watch → chuột phải symbol → Specification → Sessions → cột **Quotes**, theo giờ server. Ví dụ `Mon-Fri 00:00-23:00`; nhiều khoảng: `Mon 01:00-24:00; Tue-Fri 00:00-12:00, 13:00-23:00`. Ngày không ghi = đóng cả ngày.
- `GT_BROKER_SERVER_TZ`: múi giờ server dạng IANA (giống `GT_SERVER_TZ` của Gateway).
- Chỉ áp dụng cho MT5/CSV; dữ liệu mẫu luôn dùng lịch tham chiếu. Sai cú pháp hoặc thiếu múi giờ → backend **không khởi động**.

**Lý do (2026-11-05, MT5 demo thật MetaQuotes-Demo):** broker báo giá Mon–Fri 00:00–23:00 giờ server, tức nghỉ thêm 23:00–24:00 server (16:00–17:00 NY). Với lịch tham chiếu, mỗi ngày "thiếu" 4 nến không bao giờ tồn tại, độ phủ cửa sổ 300 nến luôn ~96% nên analyst **bị chặn vĩnh viễn**, và trang Thị trường báo nhầm "giá cũ" mỗi ngày một giờ. Mô hình giao hai lịch khớp chính xác dữ liệu thật: 5.000 nến có, 210 nến "thiếu" so với lịch tham chiếu (kể cả tuần 26–30/10 khi châu Âu đã đổi giờ còn Mỹ chưa, lúc đó không thiếu nến nào), 0 nến ngoài giờ.

**Vì sao dùng lịch chính thức chứ không tự suy từ dữ liệu:** suy lịch từ dữ liệu sẽ biến một sự cố mất dữ liệu lặp lại thành "giờ nghỉ" và che mất nó. Giao hai lịch chỉ có thể *bớt* nến lẽ ra phải có ở chỗ broker công bố là đóng. Lưới an toàn cho khai báo sai: nếu có nến thật ở chỗ lịch nói đóng cửa thì chặn bằng `CALENDAR_MISMATCH`. Mất dữ liệu giữa phiên vẫn bị R2 bắt như cũ (có test).

### Ngày lễ / đóng sớm và giờ đặc biệt của broker (từ `technical-1.3.0`, GĐ1 bước 2, 2026-11-07)

Lịch đầy đủ = tham chiếu tuần ∩ (giờ đặc biệt broker của ngày đó **nếu có**; nếu không: giờ tuần của broker **trừ** khoảng nghỉ trong bảng ngày lễ).

- **Bảng ngày lễ Mỹ** (`market/holidays.py`, phiên bản `us-holidays-2026.11.07`, năm 2024–2027), giờ New York: `CLOSED` ngày D = nghỉ `[D−1 17:00, D 18:00)` (Good Friday, Giáng sinh, năm mới); `EARLY_CLOSE` = nghỉ `[D giờ đóng, D 18:00)`: ngày lễ thứ Hai, Juneteenth, Độc lập, Lễ Tạ ơn ngừng **14:30 NY** (13:30 CT); ngày sau Lễ Tạ ơn và đêm Giáng sinh **13:45 NY** (12:45 CT). Lễ rơi thứ Bảy → nghỉ bù thứ Sáu, Chủ nhật → thứ Hai; năm mới rơi thứ Bảy không nghỉ bù. Nguồn: lịch nghỉ lễ thường lệ của CME Globex cho kim loại (`CME_PATTERN`, **chưa đối chiếu broker**); riêng Labor Day 07/09/2026 đã khớp dữ liệu thật MetaQuotes-Demo (`BROKER_DATA`: ngừng 14:30 NY, thiếu thêm đúng 6 nến M15). Test so bảng với quy tắc lịch Mỹ tính độc lập (thuật toán Phục sinh, thứ Hai thứ n…).
- **Giờ đặc biệt broker** (CAL-05): `GT_BROKER_SPECIAL_HOURS="2026-12-24 00:00-20:45; 2026-12-25 CLOSED"` (ngày + giờ **server**, chép từ thông báo của broker) và nhãn `GT_BROKER_SPECIAL_HOURS_VERSION`. Ngày có giờ đặc biệt thì giờ này thay cho giờ tuần broker **và** bảng ngày lễ (thông báo của broker cụ thể hơn bảng chung), vẫn giao với lịch tham chiếu tuần. Phiên bản = nhãn + 8 ký tự băm nội dung. Sai cú pháp, trùng ngày, thiếu `GT_BROKER_SESSIONS` → backend **không khởi động**.
- **Phiên bản lịch** (bảng + giờ đặc biệt) nằm trong `features.input.calendar` của mỗi kết quả; `features.input.holidays_in_window` liệt kê ngày lễ trong cửa sổ.
- **Cờ mới:** `LOW_LIQUIDITY_HOLIDAY` (rủi ro, chỉ gắn cờ, không đổi confidence) khi nến cuối thuộc ngày lễ/đóng sớm hoặc ngày giao dịch 24/12 → 02/01 (1B-C04). `HOLIDAY_TABLE_MISMATCH` (chất lượng, kèm `CALENDAR_MISMATCH` hoặc `LOW_COVERAGE` vẫn chặn như cũ) khi nến lệch lịch / nến thiếu rơi vào ngày lễ trong bảng: gợi ý người dùng nhập giờ đặc biệt (1B-C03).
- **Ngoài các năm của bảng:** không đoán ngày lễ (coi là ngày thường → R2 có thể chặn oan, hướng an toàn); backend ghi cảnh báo khi bảng không phủ tới 60 ngày tới.
- **Vì sao sai bảng vẫn an toàn:** ghi đóng mà broker vẫn báo giá → có nến lúc "đóng cửa" → `CALENDAR_MISMATCH` chặn; ghi mở mà broker đóng → thiếu nến → R2 chặn. Bảng chỉ *bớt* nến lẽ ra phải có ở khoảng ghi rõ trong bảng, nên mất dữ liệu ngoài khoảng đó vẫn bị bắt (có test mất nến buổi sáng Labor Day).
- **CAL-04 — cờ `GAP_BEFORE` lúc nạp** dùng lịch đầy đủ (của `MarketDataService`), **R1** dùng phần **tuần** (tham chiếu ∩ giờ tuần broker), cố ý **không** dùng bảng ngày lễ: R1 từ chối cả lô, nên một dòng sai trong bảng (ví dụ broker vẫn báo giá Good Friday: 92 nến/lô 2.000 = 4,6% > 1%) sẽ chặn nạp toàn bộ dữ liệu. Sai lệch ngày lễ đã có `CALENDAR_MISMATCH`/R2 bắt ở bước phân tích.
- **Dữ liệu mẫu** sinh theo cùng lịch tham chiếu có ngày lễ (không sinh nến trong khoảng nghỉ lễ).

**Lý do `technical-1.3.0`:** "nến lẽ ra phải có" thay đổi → độ phủ R2 và `CALENDAR_MISMATCH` thay đổi. Soát lại trên dữ liệu tổng hợp theo lịch broker thật 10/11/2026 → 08/01/2027 (chạy analyst mỗi giờ, 747 lần): lịch mới chặn 0 lần; lịch cũ chặn oan 244 lần quanh Lễ Tạ ơn, Giáng sinh, năm mới.

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
| `levels` | Gom các swing đã xác nhận trong cửa sổ thành vùng giá: giá kế tiếp vào vùng khi cách giá cao nhất của vùng ≤ 0,5 × atr14 **và** độ rộng vùng ≤ 1 × atr14 (từ `technical-1.2.0`); mỗi vùng có số lần chạm. Giữ các vùng chạm ≥ 2 lần. **Bỏ swing nằm trên nến spike (R3)** |
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

### Thay đổi `technical-1.2.0` (2026-11-05, sau khi chạy dữ liệu MT5 thật)

- **Giới hạn độ rộng vùng S/R ≤ 1 ATR.** Trên dữ liệu MetaQuotes-Demo, cách gộp cũ (chỉ xét khoảng cách tới swing liền trước) nối dây chuyền các swing cách nhau đều đặn thành vùng 3.891–3.951 (rộng ~60$, ~5 ATR, 27 lần chạm). Vùng như vậy không có ý nghĩa hỗ trợ/kháng cự và làm khoảng cách `distance_atr` sai. 1 ATR đủ chứa dao động quanh một mức giá nhưng vẫn tách các mức khác nhau.
- **Bỏ swing trên nến spike.** Nến mở lại sau giờ nghỉ ngày 04/11 có râu cắm ~150$; giá cực trị của nến lỗi feed không phải mức giá được thị trường xác nhận. Cách làm theo hướng an toàn: mất bớt thông tin (ít swing hơn) chứ không tạo mức giả. Hệ quả: swing thật trong phạm vi 3 nến quanh spike có thể không được nhận ra.

## 8. Giới hạn đã biết

- **Lịch broker nhập tay:** MT5 Python không đọc được Sessions, nên phải chép tay từ Specification. Broker đổi giờ báo giá thì phải sửa `.env`; nếu broker mở *dài* hơn khai báo, `CALENDAR_MISMATCH` sẽ chặn; nếu broker đóng *sớm* hơn khai báo, R2 sẽ chặn. Cả hai đều theo hướng an toàn.
- **Ngày lễ (từ `technical-1.3.0`):** bảng ngày lễ nhập tay, chỉ 2024–2027, giờ lễ theo thông lệ CME (chỉ Labor Day 2026 đã đối chiếu broker). Broker khác bảng → bị chặn (`CALENDAR_MISMATCH`/R2 + gợi ý `HOLIDAY_TABLE_MISMATCH`) tới khi người dùng nhập `GT_BROKER_SPECIAL_HOURS`; tối đa ~3 ngày (cửa sổ 300 nến). Cần đối chiếu từng ngày lễ đầu tiên với dữ liệu thật (Lễ Tạ ơn 26–27/11/2026, Giáng sinh, năm mới). Ngày nghỉ đột xuất (quốc tang…) không có trong bảng.
- Ngưỡng R2–R6 mới được kiểm tra trên dữ liệu mẫu; **phải kiểm tra lại trên CSV thật của broker**.
- Không có xác suất và không có tín hiệu. Fusion/Strategy không được coi `trend` là lệnh mua/bán khi chưa có backtest.

## 9. `technical-1.4.0` (GĐ3 bước 7a, 2026-11-14) — TEC-07 + TEC-09

Code: `analysts/technical_ext.py`; nạp khung lớn trong `TechnicalRunner` (công cụ replay GĐ2 dùng chung → cùng đầu vào). Test: `tests/test_technical_ext.py`.

- **`vol_forecast` (TEC-07):** EWMA λ = 0,94 (RiskMetrics) trên lợi suất log M15 của cửa sổ 300 nến; phương sai khởi đầu = trung bình r² của 30 lợi suất đầu; cần ≥ 60 lợi suất. Ra `sigma_bar_pct` (nến kế tiếp) và `sigma_day_pct` (× √96). **Luật cố định, không phải mô hình đã kiểm định, không phải xác suất**; λ chưa hiệu chỉnh cho vàng M15.
- **Đa khung (TEC-09):** H1 / H4 / D1 **cùng nguồn giá**, đã biết lúc tính, **chỉ nến đóng trước `as_of`** của M15; xu hướng theo **đúng luật xu hướng M15** (EMA20/50 + độ dốc EMA50 ≥ 0,1 ATR / 10 nến), cần ≥ 70 nến. Khung cũ khi nến cuối đóng cách `as_of` quá **một nến + 30 phút thị trường mở** (đếm theo lịch thị trường → cuối tuần không bị coi là cũ) → `STALE`, không dùng. Trạng thái mỗi khung: `OK` / `STALE` / `MISSING` / `INSUFFICIENT_HISTORY` / `NOT_EVALUATED`. `mtf_alignment`: `ALIGNED_UP` / `ALIGNED_DOWN` (mọi khung dùng được cùng chiều M15), `CONFLICT` (có khung ngược chiều), `MIXED`, `NOT_EVALUATED`; driver `MTF_<…>`. Mô tả, không phải tín hiệu.
- Băm đầu vào gồm trạng thái + nến cuối từng khung → nến khung lớn mới đến → `output_id` mới.
- **Kiểm chứng:** 14 test (EWMA tham chiếu tay: lợi suất ±r → σ = r; phản ứng cú sốc; thiếu lịch sử; xu hướng lên / xuống; nến khung lớn đóng sau `as_of` không dùng; cuối tuần không cũ / giữa tuần trễ 3 giờ → cũ; thiếu / ít nến / không đánh giá; bảng `alignment`; tích hợp runner + idempotent). **Lỗi tìm được:** thời điểm nến khung lớn (`datetime`) lọt vào đặc trưng → **Technical sẽ lỗi khi lưu** — đã sửa (chuỗi ISO). **Soát Postgres:** 96 nến, khung lớn đến trễ 5 giây – 3 phút → 192 lượt dùng, 0 nhìn trước; **công cụ replay GĐ2 so 96 / lệch 0**; σ khớp numpy + pandas `ewm` độc lập.
