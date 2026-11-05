# 04 — Các analyst độc lập

## Hợp đồng chung

Mỗi analyst nhận input point-in-time và trả output có `analystId`, `asOf`, `expiresAt`, `confidence`, `features`, `drivers`, `riskFlags`, `sourceStatus`, `qualityFlags` và `version`. Output quá hạn không được Fusion sử dụng.

## 1. Technical analyst

- **Input:** OHLC/tick đã đóng nến, spread và volatility.
- **Xử lý:** tính swing, hỗ trợ/kháng cự, pattern, ATR; LightGBM có thể ước lượng `pUp`, `pDown`.
- **Output:** bias ngắn hạn, xác suất, mức giá cấu trúc, `volForecast` và thời điểm hết hạn theo timeframe.
- **Kiểm soát:** chỉ dùng nến đóng; feature không được rò rỉ nến tương lai; kiểm tra calibration của xác suất.

## 2. News analyst (LLM)

- **Input:** tin đã khử trùng lặp và nhận diện thực thể.
- **Xử lý:** FinBERT lọc trước; LLM chỉ trích xuất stance, tác động lên vàng, novelty và bằng chứng từ nội dung.
- **Output:** sentiment/stance có cấu trúc, horizon, mức tác động, `newsShock` và liên kết bài gốc.
- **Kiểm soát:** giới hạn token/timeout, chống prompt injection từ nội dung tin, không dùng LLM ở fast lane, lưu prompt/model version và citation.

## 3. Event & calendar analyst

- **Input:** lịch và số liệu actual/forecast/previous.
- **Xử lý:** quy tắc cứng so sánh actual–forecast, phân loại FOMC/NFP/CPI và cửa sổ rủi ro trước/sau công bố.
- **Output:** `eventRisk`, surprise direction, thời điểm kết thúc cửa sổ và cờ giao dịch hạn chế.
- **Kiểm soát:** không cần LLM; phân biệt "chưa công bố" với actual bằng 0.

## 4. Macro analyst

- **Input:** DXY, real yield 10Y, kỳ vọng lãi suất Fed và series vĩ mô.
- **Xử lý:** đồng bộ theo thời điểm công bố, tính thay đổi/độ bất thường và quan hệ có điều kiện với vàng.
- **Output:** macro bias, drivers, độ tin cậy và cờ stress thanh khoản/vĩ mô.
- **Kiểm soát:** dữ liệu tần suất thấp phải có TTL phù hợp; revision không được viết lại quyết định quá khứ.

## 5. Positioning & sentiment analyst

- **Input:** COT, ETF flow và proxy tâm lý đáng tin cậy.
- **Xử lý:** chuẩn hóa z-score lịch sử, nhận diện cực trị và giả thuyết contrarian.
- **Output:** positioning bias theo horizon dài hơn, crowding risk và confidence.
- **Kiểm soát:** COT có độ trễ lớn, không được diễn giải như dữ liệu thời gian thực.

## 6. Regime analyst

- **Input:** returns, volatility, trend/range features, liquidity và output technical.
- **Xử lý:** HMM hoặc classifier phân loại `TREND|RANGE|RISK_OFF|HIGH_VOL`.
- **Output:** regime, xác suất, feature health và trọng số gợi ý cho Fusion.
- **Kiểm soát:** giám sát drift và chuyển regime; confidence thấp khi xác suất lớp gần nhau.
