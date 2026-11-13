# Thiết kế — Lãi suất từ H.15 của Fed (GĐ1 bước 9b: ING-11, ING-25, ING-26)

> Code: `backend/src/gold_trading/ingestion/sources/fed_h15.py`. Test: `backend/tests/test_fed_h15.py` (trang thật `tests/fixtures/fed/h15-2026-11-12.html`). Lệnh: `python -m gold_trading.ingestion.cli h15 [--dry-run]`. Chạy tự động trong bộ chạy nguồn ngoài (`16-…`), tên nguồn `fed_h15`.

## 1. Vì sao H.15, không phải FRED

Điều khoản FRED (đọc nguyên văn 2026-11-13, `11-dieu-khoan-nguon.md#fred`) cấm lưu nội dung FRED vào database và cấm dùng cho AI → `BLOCKED`. Người dùng chọn **trang phát hành H.15 của Hội đồng Thống đốc Fed** (`www.federalreserve.gov/releases/h15/`): public domain, ghi nguồn Board (`fed` `VERIFIED`), không cần khóa. Kiểm từ máy người dùng (Docker, 2026-11-13): HTTP 200, trang đúng.

Không dùng "Data Download Program" của Fed: Fed thông báo (12/11/2026) bỏ gói tải sẵn 31/3/2027 và gỡ trang 1/7/2027.

**Nguồn gốc số:** lợi suất trái phiếu danh nghĩa + TIPS do **Bộ Tài chính Mỹ** tính (chú thích 9, 10 của H.15: "Source: U.S. Treasury") → ghi nguồn cả hai trên web. Bộ Tài chính công bố cùng ngày (H.15 trễ 1 ngày); điều khoản trang Bộ Tài chính chưa đọc được (`NEEDS_REVIEW`) nên chưa lấy trực tiếp — có thể đổi sau khi đọc được, để giảm độ trễ.

## 2. Series

| Mã | Dòng trên trang | Dùng cho |
| --- | --- | --- |
| `EFFR` | Federal funds (effective) | ING-27 (proxy kỳ vọng Fed, 9c) |
| `UST_CMT_2Y` | Treasury constant maturities › Nominal › 2-year | ING-26, ING-27 |
| `UST_CMT_10Y` | … › Nominal › 10-year | ING-26 |
| `UST_TIPS_10Y` | … › Inflation indexed › 10-year | ING-25 (lợi suất thực) |

Khóa dữ kiện `<mã>:<ngày quan sát>`. Giá trị lưu **chuỗi đúng như trang** ("4.73"), đơn vị `PERCENT_PER_YEAR`.

Dòng được nhận bằng **đường dẫn nhóm** dựng từ thuộc tính `headers` của bảng (chính xác cha–con), không theo độ thụt (độ thụt trên trang nhảy cấp, vd. 0 → 2) và không theo vị trí dòng.

## 3. Thời gian (point-in-time, 1E-C01)

- `event_time` = hết ngày quan sát (0:00 giờ New York hôm sau).
- Trang chỉ ghi **ngày** phát hành ("Release date: November 12, 2026"), không ghi giờ → **không đoán giờ**: `available_at` để trống, hệ thống chỉ biết số từ lúc tải (`known_at = ingested_at`). Hệ quả: backtest không thấy số trước lúc hệ thống thật sự tải — an toàn, đánh đổi là chậm vài giờ.
- Ngày phát hành ở tương lai so với lúc tải, hoặc cột ngày ≥ ngày phát hành → `INVALID`.

## 4. Ô không có số (1E-C02)

| Ô | Ghi |
| --- | --- |
| Số `d.dd` trong [-5, 25] | `AVAILABLE` |
| `n.a.` | `value = None`, `NOT_AVAILABLE` |
| Trống ở cột có `*` (thị trường đóng, vd. 11/11 Veterans Day) | `value = None`, `MARKET_CLOSED` |
| Trống ở cột thường | chưa công bố → **không ghi** |

Không nội suy, không bao giờ coi trống là 0.

## 5. Từ chối cả lần tải (không ghi gì → `INVALID`)

Thiếu ngày phát hành / bảng `h15table`; thiếu một trong 4 dòng hoặc đổi tên nhóm (1E-C03: Fed đổi tên / ngừng series); dòng trùng; số ô khác số cột; cột ngày sai thứ tự / trùng / không tồn tại / lệch ngày phát hành quá 21 ngày; số sai định dạng (`473`, `4,73`, `4.7`) hoặc ngoài [-5, 25] % (1E-C04: nghi đổi đơn vị).

## 6. Sửa số + nạp lại

Giá trị hoặc trạng thái đổi → revision mới (quá khứ giữ số cũ; ô `MARKET_CLOSED` sau có số → revision). Bản phát hành **cũ hơn** bản đã ghi số đó → không viết lại. Nạp lại cùng trang → không thêm gì.

## 7. Lịch tải + trạng thái

Tải lại khi lần OK cuối > 4 giờ; lỗi → thử lại sau 30 phút. `fetch_ttl` 30 giờ; `data_ttl` 7 ngày (số mới nhất bình thường là ngày làm việc trước; lễ + cuối tuần + trễ 1 ngày ~4–5 ngày) → quá hạn STALE. H.15 không phải "tin công bố" cần bắt từng phút: là bối cảnh vĩ mô hằng ngày.

## 8. Kiểm chứng

Số đọc được khớp file CSV của Fed (gói Treasury Constant Maturities) và **file CSV của chính Bộ Tài chính Mỹ** (lợi suất danh nghĩa + thực): 12/12 số khớp (2026-11-05..10). EFFR chưa đối chiếu nguồn độc lập (gốc ở Fed New York, chưa nằm trong danh sách trang được phép tải).

## 9. Proxy kỳ vọng lãi suất Fed (9c — ING-27, DEC-04, 2026-11-13)

Code `backend/src/gold_trading/ingestion/macro_view.py` (`fed_expectation_proxy(store, as_of)`), phiên bản `fed-proxy-2026.11.13`; in kèm lệnh `cli h15`.

- **Công thức (DEC-04, người dùng chốt):** `chênh lệch = UST_CMT_2Y − EFFR` cùng **một ngày quan sát**, tính bằng `Decimal` trên chuỗi H.15; ra điểm % và điểm cơ bản. `< 0` → `LEANS_CUT`, `> 0` → `LEANS_HOLD_OR_HIKE`, `= 0` → `FLAT`.
- **Không phải xác suất:** không quy đổi thành "% khả năng Fed cắt lãi" (chưa hiệu chỉnh); nhãn ghi rõ "proxy … không phải xác suất".
- **Không dải trung tính:** DEC-04 chỉ định theo dấu; chênh vài điểm cơ bản quanh 0 vẫn đổi nhãn. Ai dùng (GĐ3–4) nên dùng số `spread_bp`, không chỉ nhãn — có thêm dải trung tính thì phải là quyết định mới của người dùng.
- **Ghép ngày:** chỉ ngày có **cả hai** số (`AVAILABLE`); ngày thị trường trái phiếu đóng mà EFFR vẫn có → lùi về ngày chung trước đó. Không bao giờ trộn hai ngày.
- **Không đủ dữ liệu:** không có ngày chung (`NO_COMMON_DAY`) hoặc ngày chung cũ hơn 7 ngày so với `as_of` (`STALE`, cùng mức `data_ttl` của nguồn) → `INSUFFICIENT_DATA`, không trả số.
- Tính khi đọc từ bản ghi point-in-time (không lưu) → cùng `as_of` cho cùng kết quả; Fed sửa số → proxy đổi từ lúc hệ thống biết bản sửa, quá khứ giữ nguyên.
- **Kiểm chứng:** ngày 10/11/2026: 4.73 − 3.88 = +0.85 (+85 điểm cơ bản), tính tay độc lập từ CSV lợi suất của Bộ Tài chính Mỹ cũng ra 0.85.
