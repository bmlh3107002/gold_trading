# GĐ3 — 6 analyst độc lập (đặc tả 04), bản luật (ML để GĐ7)

> **Bắt đầu 2026-11-14 song song GĐ1 + GĐ2 (DEC-22).** Kế hoạch + checklist: [`docs/ke-hoach/GD3-ke-hoach.md`](../ke-hoach/GD3-ke-hoach.md).
>
> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


### Quyết định GĐ3

| Mã | Câu hỏi | Người dùng chốt | TT |
| --- | --- | --- | --- |
| DEC-22 | Bắt đầu GĐ3 khi GĐ1 / GĐ2 chỉ còn kiểm trên máy / chờ ngày công bố | Người dùng 2026-11-14: **có, kế hoạch trước** — viết `GD3-ke-hoach.md`, làm analyst **Lịch sự kiện** đầu tiên. Ngoại lệ có chủ ý cho "đi sạch từng giai đoạn" (như DEC-19). **Không đóng GĐ3 trước GĐ1 rồi GĐ2**; việc kiểm trên máy GĐ1/GĐ2 được ưu tiên | `[x]` 2026-11-14 |

Hợp đồng chung (`contracts/analyst.py`): `analystId`, `asOf`, `expiresAt`, `confidence`, `features`, `drivers`, `riskFlags`, `sourceStatus`, `qualityFlags`, `version`. Mỗi analyst có thiết kế riêng ở `docs/thiet-ke/`. **Không có xác suất khi chưa hiệu chỉnh.**

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ANA-01 | Khung chung: hết hạn, trạng thái nguồn, phiên bản, lưu append-only cho mọi analyst | `[x]` | 2026-11-14: `analysts/framework.py` + `append_scoped`/`latest_scoped` (`storage/analyst_outputs.py`); thiết kế `docs/thiet-ke/27-khung-analyst.md`. Technical giữ đường cũ (chưa chuyển sang khung — không đổi kết quả) |
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
| 3-C01 | Thiếu input bắt buộc | `sourceStatus=MISSING`, không xuất đặc trưng | `[~]` Technical + khung chung (bước 1); mỗi analyst mới tick khi có test riêng |
| 3-C02 | Input quá cũ | STALE | `[~]` Technical + khung chung (bước 1); mỗi analyst mới tick khi có test riêng |
| 3-C03 | Chưa đủ lịch sử | `INSUFFICIENT_HISTORY` | `[~]` Technical + khung chung (bước 1); mỗi analyst mới tick khi có test riêng |
| 3-C04 | Giá trị cực đoan / spike trong input | Gắn cờ, hạ độ tin cậy | `[~]` Technical + khung chung (bước 1); mỗi analyst mới tick khi có test riêng |
| 3-C05 | Dữ liệu SAMPLE | Cờ `SAMPLE_DATA` | `[~]` Technical + khung chung (bước 1); mỗi analyst mới tick khi có test riêng |
| 3-C06 | Thêm dữ liệu tương lai rồi tính lại tại thời điểm cũ | Kết quả không đổi | `[~]` Technical + khung chung (bước 1); mỗi analyst mới tick khi có test riêng |
| 3-C07 | Đổi công thức/ngưỡng | Tăng `version`, output cũ giữ nguyên | `[~]` Technical + khung chung (bước 1); mỗi analyst mới tick khi có test riêng |
| 3-C08 | Các nguồn của một analyst mâu thuẫn nhau | Hạ confidence, ghi driver | `[ ]` |
| 3-C09 | (Event) công bố đúng lúc thị trường đóng / cuối tuần | Cửa sổ áp dụng khi mở cửa | `[ ]` |
| 3-C10 | (News) tin chứa lệnh "bỏ qua hướng dẫn…" | Không làm theo; gắn cờ injection | `[ ]` |

**Gate GĐ3:** đủ 6 analyst có thiết kế + test case + thẻ giao diện; chạy song song trên dữ liệu thật ≥ 5 ngày giao dịch; mỗi output truy được về input.

### Nhật ký GĐ3

- **2026-11-14** — **Bước 1: khung chung analyst (ANA-01).** Thiết kế `27-khung-analyst.md`: analyst theo nguồn giá vs. toàn cục; toàn cục lưu cùng bảng `analyst_outputs` với `(*, *, GLOBAL, "")` — không migration (bảng đã chỉ-thêm từ 0003). `analysts/framework.py`: `Scope`, `input_digest` (JSON chuẩn, kiểu lạ / datetime không múi giờ / NaN → lỗi), `output_id` có phiên bản, `assess` (bắt buộc: MISSING > STALE > INVALID chặn; tùy chọn: chỉ cờ `OPTIONAL_*` — không tự đặt hệ số hạ confidence chung; cực đoan → trần 0,5 như Technical; `known_at > as_of` → `LookAheadError`), `build_output` (chặn → chỉ `features.input` để truy vết, confidence 0). Kho: `append_scoped` (chặn output khác phạm vi), `latest_scoped(known_by=)` point-in-time. 35 test (analyst mẫu: 3-C01..C07, kho bộ nhớ + SQLite). Soát riêng trên Postgres 16: ghi trùng 8 luồng → đúng 1, trigger chặn UPDATE/DELETE, 300 kết quả ngẫu nhiên → `latest_scoped` / `expired_unreplaced` / `computed_between` bộ nhớ ≡ Postgres. Giới hạn: router chưa tính lại analyst toàn cục khi hết hạn (bước 2); Technical chưa chuyển sang khung.

- **2026-11-14** — **DEC-22: bắt đầu GĐ3 song song.** Viết `docs/ke-hoach/GD3-ke-hoach.md` (8 bước: khung chung → Lịch sự kiện → Regime → Macro → Positioning → News (cần DEC-08) → Technical còn lại → Gate). Nguyên tắc: analyst chỉ quan sát, chặn lệnh vẫn do Safety / làn nhanh; analyst Lịch sự kiện dùng chung bảng lịch hợp nhất + `event_importance` với làn nhanh. Ghi nhận: phần lớn EVT-01/02 đã có từ GĐ1 (`ingestion/event_importance.py`, `economic_calendar.py`) — GĐ3 bọc thành output analyst, không viết lại chính sách.
