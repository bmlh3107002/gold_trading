# GĐ3 — 6 analyst độc lập (đặc tả 04), bản luật (ML để GĐ7)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


Hợp đồng chung (`contracts/analyst.py`): `analystId`, `asOf`, `expiresAt`, `confidence`, `features`, `drivers`, `riskFlags`, `sourceStatus`, `qualityFlags`, `version`. Mỗi analyst có thiết kế riêng ở `docs/thiet-ke/`. **Không có xác suất khi chưa hiệu chỉnh.**

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ANA-01 | Khung chung: hết hạn, trạng thái nguồn, phiên bản, lưu append-only cho mọi analyst | `[~]` | Có cho Technical (`storage/analyst_outputs.py`) |
| ANA-02 | Thẻ giao diện cho từng analyst | `[~]` | Có cho Technical |
| **Technical** | | | |
| TEC-01 | EMA, RSI Wilder, ATR Wilder (đối chiếu thư viện chuẩn) | `[x]` | `analysts/indicators.py` |
| TEC-02 | Cổng chất lượng R2–R6 + `CALENDAR_MISMATCH` | `[x]` | `market/quality.py` |
| TEC-03 | Xu hướng, cấu trúc, swing, vùng S/R (`technical-1.2.0`) | `[x]` | `docs/thiet-ke/03-technical-analyst.md` |
| TEC-04 | Lưu, API, thẻ giao diện; confidence = chất lượng dữ liệu | `[x]` | |
| TEC-05 | Theo dõi ngưỡng R3/R5 trên dữ liệu thật vài ngày | `[!]` | |
| TEC-06 | Pattern giá/nến | `[ ]` | Không rò rỉ tương lai |
| TEC-07 | `volForecast` bằng luật (ATR/EWMA), ghi rõ không phải mô hình | `[ ]` | |
| TEC-09 | Bối cảnh đa khung (H1/H4/D1) | `[ ]` | ← ING-14 |
| **Event & calendar** | | | |
| EVT-01 | Phân loại FOMC/NFP/CPI…, mức quan trọng (luật cứng, không LLM) | `[ ]` | ← ING-09, ING-20 |
| EVT-02 | Cửa sổ rủi ro trước/sau công bố → cờ `EVENT_WINDOW` (độ dài theo mức quan trọng, có phiên bản) | `[ ]` | |
| EVT-03 | Actual – forecast → hướng bất ngờ, `eventRisk` | `[ ]` | Không có forecast → "không đủ dữ liệu" |
| EVT-04 | Xử lý công bố bị hoãn/hủy/đổi giờ | `[ ]` | |
| **News (LLM)** | | | |
| DEC-08 | Chọn nhà cung cấp LLM + ngân sách | `[!]` | |
| NEWS-01 | Lọc trùng, nhận diện thực thể | `[ ]` | ← ING-10, ING-23 |
| NEWS-02 | Lọc trước (FinBERT hoặc luật) → LLM trích stance, impact, novelty, horizon, `newsShock`, có trích dẫn bài gốc | `[ ]` | |
| NEWS-03 | Giới hạn token/timeout, chống prompt injection, lưu prompt + phiên bản mô hình | `[ ]` | |
| NEWS-04 | LLM lỗi/hết ngân sách → analyst MISSING (không đoán) | `[ ]` | |
| **Macro** | | | |
| MAC-01 | Đồng bộ DXY, lợi suất thực 10Y, kỳ vọng Fed theo thời điểm công bố | `[ ]` | ← ING-24..27 |
| MAC-02 | Thay đổi/độ bất thường, macro bias, cờ stress | `[ ]` | TTL phù hợp tần suất thấp |
| **Positioning & sentiment** | | | |
| POSN-01 | Z-score lịch sử COT, ETF, NHTW | `[ ]` | ← ING-12, ING-28, ING-29 |
| POSN-02 | Crowding risk, giả thuyết contrarian ở cực trị | `[ ]` | COT trễ, không coi là thời gian thực |
| **Regime** | | | |
| REG-01 | Phân loại `TREND/RANGE/RISK_OFF/HIGH_VOL` bằng luật (biến động, độ dốc xu hướng…) | `[ ]` | Bản HMM/classifier ở GĐ7 |
| REG-02 | Trọng số gợi ý cho Fusion, theo dõi chuyển regime | `[ ]` | |

| Mã | Tình huống (áp dụng cho **mọi** analyst) | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 3-C01 | Thiếu input bắt buộc | `sourceStatus=MISSING`, không xuất đặc trưng | `[~]` (Technical) |
| 3-C02 | Input quá cũ | STALE | `[~]` (Technical) |
| 3-C03 | Chưa đủ lịch sử | `INSUFFICIENT_HISTORY` | `[~]` (Technical) |
| 3-C04 | Giá trị cực đoan / spike trong input | Gắn cờ, hạ độ tin cậy | `[~]` (Technical) |
| 3-C05 | Dữ liệu SAMPLE | Cờ `SAMPLE_DATA` | `[~]` (Technical) |
| 3-C06 | Thêm dữ liệu tương lai rồi tính lại tại thời điểm cũ | Kết quả không đổi | `[~]` (Technical 40/40) |
| 3-C07 | Đổi công thức/ngưỡng | Tăng `version`, output cũ giữ nguyên | `[~]` |
| 3-C08 | Các nguồn của một analyst mâu thuẫn nhau | Hạ confidence, ghi driver | `[ ]` |
| 3-C09 | (Event) công bố đúng lúc thị trường đóng / cuối tuần | Cửa sổ áp dụng khi mở cửa | `[ ]` |
| 3-C10 | (News) tin chứa lệnh "bỏ qua hướng dẫn…" | Không làm theo; gắn cờ injection | `[ ]` |

**Gate GĐ3:** đủ 6 analyst có thiết kế + test case + thẻ giao diện; chạy song song trên dữ liệu thật ≥ 5 ngày giao dịch; mỗi output truy được về input.
