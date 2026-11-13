# Thiết kế — Chỉ số USD tự tính (GĐ1 bước 9d: ING-24, DEC-03, DEC-14)

> Code: `backend/src/gold_trading/market/usd_index.py`. Test: `backend/tests/test_usd_index.py`. Lệnh: `python -m gold_trading.ingestion.cli usd [--server …]` (chỉ đọc DB). Dữ liệu đầu vào: nến M15 của 6 cặp do Gateway gửi từ bước 5d (`09a` mục 5f).

## 1. Công thức + nhãn

`I = 50.14348112 × EURUSD^-0.576 × USDJPY^0.136 × GBPUSD^-0.119 × USDCAD^0.091 × USDSEK^0.042 × USDCHF^0.036` (công thức công khai của chỉ số đô la Mỹ; trọng số tuyệt đối cộng lại = 1). Tính bằng tổng log rồi lũy thừa (float); phiên bản `usd-index-6pairs-2026.11.13`.

**Nhãn bắt buộc:** "chỉ số USD tự tính (công thức 6 cặp như DXY, giá broker — không phải DXY chính thức)". Giá trị lệch DXY vì dùng giá **của broker người dùng** (bid/đóng cửa nến), không phải giá liên ngân hàng của nhà cung cấp chỉ số.

## 2. Dữ liệu dùng

- **Theo broker (DEC-14):** 6 nguồn giá cùng **server MT5** (`price_feeds`, không phân biệt hoa/thường). Không bao giờ trộn hai broker — broker A không có nến mới thì không mượn nến của broker B.
- Tìm nguồn của cặp: symbol broker **chứa** tên cặp (cùng quy tắc Gateway), bỏ symbol có `XAU`. Một cặp có nhiều symbol (vd. đổi hậu tố `EURUSD` → `EURUSD.r`; `price_feeds` chỉ thêm, không xóa) → chọn symbol có nến mới nhất; hai symbol cùng có nến mới nhất → `AMBIGUOUS_FEED`.
- **Point-in-time:** chỉ nến M15 **đã đóng** (`close_time ≤ as_of`) và đã biết (`available_at ≤ as_of`), bản sửa (revision) mới nhất đã biết.
- **Cùng thời điểm:** giá đóng cửa của **cùng một nến** (cùng `open_time`) cho cả 6 cặp — nến chung mới nhất trong 16 nến gần nhất (4 giờ). Cặp nào đã có nến mới hơn nến chung → cờ `<cặp>:NEWER_BAR_NOT_COMMON`.

## 3. Không đủ dữ liệu (`INSUFFICIENT_DATA`, không nội suy)

| Lý do | Khi nào |
| --- | --- |
| `PAIR_MISSING` | Server không có nguồn (hoặc chưa có nến nào) của một cặp |
| `PAIR_NO_DATA` | Cặp có nguồn nhưng chưa có nến đã đóng / đã biết trong 4 giờ |
| `NO_COMMON_BAR` | 6 cặp không có nến nào cùng `open_time` |
| `STALE` | Nến chung mới nhất đóng cách `as_of` **quá 30 phút** (cuối tuần, mất kết nối, một cặp ngừng) |
| `PAIR_OUT_OF_RANGE` | Giá một cặp ngoài khoảng rất rộng (vd. USDJPY 50–400, USDSEK 4–20): nghi nhầm symbol / báo giá đảo chiều / đổi đơn vị |
| `AMBIGUOUS_FEED` | Hai symbol broker cùng một cặp đều có nến mới nhất |

**Lý do 30 phút:** chỉ số dùng làm bối cảnh trong ngày cho vàng (M15); quá 2 nến thì không còn là "hiện tại". Đánh đổi: thiếu một nến của **một** cặp (Gateway lỗi riêng cặp đó) làm chỉ số thành "không đủ dữ liệu" tới khi có nến chung mới — chọn an toàn hơn là ghép giá khác thời điểm.

## 4. Cờ cảnh báo (vẫn tính)

Cờ nến đầu vào `PRICE_JUMP`, `ZERO_RANGE`, `REVISED`, `GAP_BEFORE` chuyển lên chỉ số dạng `<cặp>:<cờ>`.

## 5. Kiểm chứng

- Test: so với tính tay bằng lũy thừa trực tiếp; mọi cặp = 1 → đúng hằng số; USD mạnh lên → chỉ số tăng.
- Soát lại: 2.000 bộ giá ngẫu nhiên so với `Decimal` 50 chữ số — sai số tương đối lớn nhất 2×10⁻¹⁵; một ngày nến có lỗ hổng + trễ ngẫu nhiên trên Postgres, đi từng phút: 0 lỗi bất biến (không dùng nến chưa đóng / chưa biết, luôn nến chung mới nhất, không báo thiếu sai, không quá 30 phút).
- **Chưa:** đối chiếu với symbol chỉ số USD của broker (nếu broker có — DEC-03) và với DXY thật — kiểm trên máy người dùng (mục 16).

**Chưa làm:** lưu chuỗi chỉ số / hiển thị web (dùng ở GĐ3–4 khi cần); tính theo H1/H4/D1.
