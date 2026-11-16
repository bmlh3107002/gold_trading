# GĐ5 — Kế hoạch giao dịch: hồ sơ rủi ro + chiến lược + Risk Engine + Ledger (đặc tả 06, 07)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


> **DEC-28 (người dùng 2026-11-16): mở GĐ5 song song** khi GĐ1–GĐ4 chỉ còn kiểm trên máy / chờ ngày (ngoại lệ có chủ ý cho "đi sạch từng giai đoạn", như DEC-19, DEC-22, DEC-23). Điều kiện: **viết kế hoạch trước ở phiên chat mới** (`docs/ke-hoach/GD5-ke-hoach.md`), **người dùng duyệt rồi mới code**; **không đóng GĐ5 trước GĐ1 → GĐ2 → GĐ3 → GĐ4**; việc kiểm trên máy của các giai đoạn trước được ưu tiên; **không có lệnh thật nào** (GĐ5 chỉ tạo ý định + quyết định Risk, chưa gửi lệnh — gửi lệnh từ GĐ8/GĐ9); không tự đặt số rủi ro — chờ tài liệu quản lý vốn của người dùng (KN-12, DEC-09); RSK-10, RSK-11 (KN-01, KN-02) là việc **bắt buộc** đầu GĐ5. Code GĐ5 không lên `develop` trong đợt đếm 5 ngày của GĐ1 nếu người dùng chưa chọn lịch dựng lại.

### 5A — Hồ sơ rủi ro (việc ③b)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| DEC-09 | Người dùng trả lời: vốn; mục tiêu 4–5% theo ngày/tuần/tháng; lỗ tối đa mỗi lệnh; ngưỡng dừng ngày/tuần; giữ lệnh trong ngày hay qua đêm; broker, đòn bẩy, phí | `[~]` | **Nguyên tắc đã chốt 2026-11-14 (người dùng):** khi mục tiêu lợi nhuận mâu thuẫn rủi ro → **ưu tiên rủi ro mỗi lệnh**: luật cứng của Risk Engine là rủi ro **0,25–0,5 % vốn / lệnh** + ngưỡng lỗ ngày / tuần; mục tiêu 4–5 %/ngày **chỉ là con số tham khảo**, không bao giờ dùng để nới rủi ro, tăng lot hay ép hệ thống vào lệnh. Con số cụ thể (mức trong khoảng 0,25–0,5 %, ngưỡng dừng, giữ qua đêm…) và các chương áp dụng từ tài liệu "Quản lý vốn khi trade vàng" chốt khi người dùng gửi lại tài liệu (chưa có trong repo) — tại GĐ5 |
| DB-07 | Bảng hồ sơ rủi ro có phiên bản | `[ ]` | |
| RPF-01 | Hồ sơ rủi ro có phiên bản (append-only, audit) | `[!]` | ← DEC-09 |
| RPF-02 | Đề xuất SL theo ATR, TP theo R:R, lot theo rủi ro, thời gian giữ lệnh ước tính | `[ ]` | Lot làm tròn **xuống**; < tối thiểu → **không khả thi** |
| RPF-03 | Kết luận khả thi bằng số cụ thể | `[ ]` | Ví dụ: vốn 100$, ATR ~13$, lot 0,01 → SL 1,5 ATR mất ~20% vốn |
| RPF-04 | Nhãn "chỉ minh họa" khi SAMPLE | `[ ]` | |
| RPF-05 | Trang nhập hồ sơ và xem kế hoạch | `[ ]` | Thuộc trang Rủi ro (DSH-05) |

### 5B — Chiến lược (Strategy Engine)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| STR-06 | **Văn bản chiến lược v1** được người dùng duyệt: điều kiện vào/ra, phiên giao dịch, cửa sổ cấm, SL/TP, BE, trailing, time-stop, số lệnh tối đa | `[ ]` | `docs/thiet-ke/` |
| STR-01 | Contract `TradeIntent` (SL/TP đúng chiều lệnh) | `[x]` | `contracts/trade_intent.py` |
| STR-02 | Điều kiện vào: MarketView còn hạn, confidence đạt ngưỡng theo regime, không có riskFlags cấm | `[ ]` | `strategy/` |
| STR-03 | Sinh intent: entry, SL, TP, `riskBudgetRequested`, `expiry`, `idempotencyKey` | `[ ]` | Không tự suy volume cuối |
| STR-04 | Chống intent trùng cho cùng strategy/symbol/horizon | `[ ]` | |
| STR-05 | Audit, gửi Risk, ghi lý do khi bị từ chối | `[ ]` | |

### 5C — Risk Engine

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| CORE-05 | Tiền/PnL dùng `Decimal` | `[ ]` | Bắt buộc trước LED-04 |
| RSK-01 | Kiểm Safety, hết hạn intent/MarketView, riskFlags, spread | `[x]` | `risk/engine.py` |
| RSK-02 | Sizing theo rủi ro, volume step/min/max, hạn mức tổng (giữ `ledger.lock`) | `[x]` | |
| RSK-03 | Margin/đòn bẩy | `[ ]` | ← GW-09 |
| RSK-04 | Exposure ròng/gộp, tập trung | `[ ]` | |
| RSK-05 | Hạn mức ngày/tuần, drawdown, chuỗi thua | `[ ]` | ← RPF-01 |
| RSK-06 | Kết quả `REDUCED`, TTL quyết định, gắn policy version | `[ ]` | |
| RSK-07 | Đọc `EVENT_WINDOW`, `WIDE_SPREAD`, `HIGH_VOLATILITY` từ MarketView thật | `[ ]` | |
| RSK-08 | Stops level / freeze level của broker: SL quá gần → từ chối | `[ ]` | ← GW-09 |
| RSK-09 | Ước tính swap qua đêm (thứ Tư ×3) và commission vào rủi ro | `[ ]` | |
| RSK-10 | **Risk tự đọc cổng thật lúc quyết** (KN-01, BẮT BUỘC trước khi nối Strategy): hỏi `AccountRegistry.allows_new_orders(tài khoản)` (Safety + khóa người dùng + **lệnh cấm làn nhanh DEC-20**) và `MarketViewStore.current(nguồn, now)` (thấy MarketView bị vô hiệu); bỏ tham số `SafetySupervisor` / MarketView do bên gọi đưa | `[ ]` | Đánh giá 15/11 F-02: `risk/engine.py:73` hỏi `SafetySupervisor.allows_new_orders()` — chỉ xét ACTIVE, không thấy lệnh cấm (chỉ có ở `accounts/runtime.py:153`). Ghi chú RSK-01 `[x]` chưa bao gồm DEC-20. Test: lệnh cấm còn hạn + Safety ACTIVE → `REJECTED`; MarketView bị vô hiệu sau khi tạo intent → `REJECTED` |
| RSK-11 | **Khối lượng + rủi ro theo thông số thật** (KN-02, BẮT BUỘC): giá trị tick / cỡ hợp đồng / tiền tài khoản từ broker (GW-09), không hằng số `contract_size=100`; rủi ro mỗi lệnh = khoảng SL **+ spread + trượt giá ước tính + phí**; ngưỡng spread theo phân bố của chính broker thay cho `max_spread=0,5` cố định | `[ ]` | Đánh giá 15/11: `risk/engine.py:28,42,100` — rủi ro hiện chỉ tính khoảng SL → đánh giá thấp rủi ro thật. Test tính tay: tài khoản USD / khác tiền / broker 1 lot ≠ 100 oz. ← GW-09, RSK-03, RSK-09 |

### 5D — Risk Ledger (bản paper)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| LED-01 | Reserve/release append-only trong bộ nhớ, test đồng thời | `[x]` | `risk/ledger.py` |
| DB-06 | Bảng lệnh, deal, vị thế, reservation | `[ ]` | |
| LED-02 | Lưu ledger vào DB (`PortfolioState`, `RiskReservation`) | `[ ]` | |
| LED-04 | Fill/đóng lệnh → exposure và PnL (Decimal) | `[ ]` | |
| LED-05 | Khôi phục sau crash giữa reserve và gửi lệnh | `[ ]` | |
| DSH-05 | Trang Rủi ro (hồ sơ, hạn mức, mức đã dùng) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 5-C01 | Vốn quá nhỏ: lot tối thiểu vẫn vượt rủi ro cho phép | **Từ chối**, nói rõ số tiền thiếu; không làm tròn lên | `[ ]` |
| 5-C02 | SL quá gần (< spread hoặc < stops level) / quá xa | Từ chối | `[ ]` |
| 5-C03 | Tín hiệu ngược chiều khi đang có lệnh | Theo văn bản chiến lược (không tự đảo lệnh nếu chưa định nghĩa) | `[ ]` |
| 5-C04 | Nhiều tín hiệu liên tiếp / trùng | Chống trùng, giới hạn số lệnh | `[ ]` |
| 5-C05 | Chạm ngưỡng lỗ ngày/tuần | Chặn lệnh mới tới kỳ sau; Safety PAUSED | `[ ]` |
| 5-C06 | Chuỗi thua liên tiếp | Giảm rủi ro hoặc dừng theo chính sách | `[ ]` |
| 5-C07 | Giữ lệnh qua cuối tuần (gap qua SL) | Theo chính sách: cấm hoặc tính rủi ro gap | `[ ]` |
| 5-C08 | Swap qua đêm, thứ Tư ×3 | Tính vào chi phí | `[ ]` |
| 5-C09 | Margin không đủ / đòn bẩy bị broker đổi | Từ chối / giảm khối lượng | `[ ]` |
| 5-C10 | Spread giãn lúc vào / đang trong cửa sổ tin | Từ chối | `[~]` (spread) |
| 5-C11 | Intent hoặc MarketView hết hạn | Từ chối | `[x]` |
| 5-C12 | Hai intent đồng thời tiêu cùng ngân sách | Tổng không vượt hạn mức | `[x]` |
| 5-C13 | Equity đổi giữa lúc tính và lúc duyệt | Tính lại dưới khóa | `[~]` |
| 5-C14 | Lệnh cấm làn nhanh còn hạn (tin, spread giãn) trong khi Safety ACTIVE | Risk từ chối (RSK-10) | `[ ]` |
| 5-C15 | MarketView bị vô hiệu sau khi tạo intent, trước lúc duyệt | Risk từ chối (RSK-10) | `[ ]` |
| 5-C16 | Spread / phí làm lỗ thật khi chạm SL vượt mức rủi ro được duyệt | Giảm khối lượng hoặc từ chối (RSK-11) | `[ ]` |

### Tiêu chí chọn sàn giao dịch thật (phần "broker" của DEC-09 — KN-04, người dùng đồng ý ghi 2026-11-16)

Người dùng **chưa chọn sàn**. Danh sách để xem khi chọn (không gợi ý tên sàn; không có sàn "đúng" chung). Thứ tự = mức quan trọng.

1. **An toàn tiền:** giấy phép của cơ quan quản lý nghiêm (vd. FCA, ASIC, CySEC) — tra số giấy phép trên trang của chính cơ quan đó; tiền khách giữ riêng (segregated funds); chống âm tài khoản (negative balance protection); nạp / rút từ Việt Nam (cách, phí, thời gian) — rút thử khoản nhỏ trước.
2. **Lot nhỏ nhất so với luật 0,25–0,5 %/lệnh:** lot nhỏ nhất, bước lot, cỡ hợp đồng XAUUSD (oz / lot). Với 1 lot = 100 oz, SL ~19,5 USD ở 0,01 lot (ví dụ RPF-03, chưa đo thật) → cần vốn ≈ 3.900–7.800 USD; vốn nhỏ hơn → xem tài khoản **cent / micro**. Số thật tính lại ở RPF-03 bằng ATR thật (5-C01: không đủ → từ chối, không làm tròn lên).
3. **Chi phí:** spread vàng lúc thường **và lúc ra tin**; phí hoa hồng / lot (so ECN + phí với Standard không phí bằng tổng chi phí); swap (thứ Tư ×3, có swap-free không); kiểu khớp (market execution hay requote) và trượt giá.
4. **Kỹ thuật cho hệ thống:** có MT5 và cho phép chạy tự động (EA / Python); **demo cùng điều kiện với tài khoản thật**; độ dài lịch sử M15 trên MT5 (cần vài năm cho backtest — KN-04); stops / freeze level; đòn bẩy, mức margin call / stop out; múi giờ server + giờ giao dịch vàng, ngày lễ (khai `GT_BROKER_SESSIONS`, `GT_BROKER_SERVER_TZ`); điều cấm (giao dịch quanh tin, hedging, FIFO).
5. **Cách kiểm trước khi chọn (không tốn tiền), sau 24/11:** mở demo 2–3 sàn ứng viên → Gateway chạy song song (MT-15, mỗi sàn một nguồn giá — DEC-14) → sau 1–2 tuần so bằng số liệu: spread theo phút (ING-35, gồm cửa sổ tin), độ đủ dữ liệu, lịch sử có sẵn, độ ổn định kết nối.

Khi người dùng chọn xong: ghi tên sàn + loại tài khoản vào DEC-09, nạp lịch sử dài từ sàn đó (KN-04, ING-05 / `GT_HISTORY_BARS`).

**Gate GĐ5:** người dùng duyệt hồ sơ rủi ro (DEC-09) và văn bản chiến lược (STR-06); mọi case có test; báo cáo khả thi trên dữ liệu thật.

### Nhật ký GĐ5

- **2026-11-15** — Thêm **RSK-10** (KN-01) + **RSK-11** (KN-02) và case 5-C14..C16 từ đánh giá độc lập `docs/danh-gia/danh-gia-GD0-GD4.md` (người dùng duyệt). Chỉ ghi việc, chưa code — làm khi tới GĐ5, **trước** khi nối Strategy → Risk.
- **2026-11-16** — Thêm mục "Tiêu chí chọn sàn giao dịch thật" (phần broker của DEC-09, KN-04). Người dùng chưa chọn sàn; kiểm demo 2–3 sàn ứng viên sau 24/11. Chỉ tài liệu.
- **2026-11-16** — Bản nháp kế hoạch [`docs/ke-hoach/GD5-ke-hoach.md`](../ke-hoach/GD5-ke-hoach.md) (DEC-28): RSK-10 → RSK-11 đầu tiên, số rủi ro chờ KN-12, KN-07/KN-08 cuối GĐ5; 7 câu hỏi Q1–Q7 hỏi lần lượt. Chưa code — chờ người dùng duyệt.
