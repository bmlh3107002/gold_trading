# 39 — Backtest (GĐ6: BT-01, BT-02, BT-03, MOD-03) — thiết kế

> 2026-11-23 · GĐ6 bước 1 · kế hoạch [`GD6-ke-hoach.md`](../ke-hoach/GD6-ke-hoach.md) (người dùng duyệt 17/11). Giao thức **đã khóa**: [`38-giao-thuc-danh-gia.md`](38-giao-thuc-danh-gia.md) (`protocol-1`). Tham số: [`so-tham-so.md`](so-tham-so.md). Thiết kế này **không đổi** giao thức, không thêm nút vặn nào; chỗ nào phải chọn cách mô phỏng thì ghi rõ là **giả định** và đưa vào mục "Bias đã biết" của báo cáo.

## 1. Mục tiêu và giới hạn

- Trả lời đúng một câu của protocol-1: **sau khi trừ đủ chi phí, chiến lược `xu-huong-m15@1.0.0` có lợi thế thật không** — trên nến M15 thật XAUUSD của chính sàn người dùng.
- Backtest **không** là dự báo; mọi con số là **kết quả quá khứ dưới các giả định ở mục 8**. Không gọi bất kỳ số nào là "xác suất thắng" / "độ tin cậy dự báo".
- **Không có đường tới Gateway / MT5**, không ghi vào DB của hệ thống đang chạy, không ghi sổ paper thật (test khẳng định).

## 2. Nguyên tắc: chạy đúng mã đang dùng

| Thành phần | Backtest dùng | Thay gì |
| --- | --- | --- |
| 6 analyst, snapshot, Quality Gate, Fusion | **đúng mã + phiên bản hiện hành** | chỉ thay kho đọc (DB backtest riêng, point-in-time tại `t`) |
| Chiến lược | `strategy/trend_m15.py` `decide`, `Manager`, `Params` | lưới P1 / P7 / P8 = 27 `Params` |
| Risk | **`RiskEngine` thật** (đã nhận `clock` + cổng dạng hàm — `risk/gates.py` `RiskGates`) | cổng lịch sử (mục 5) + đồng hồ mô phỏng |
| Sổ lệnh | `RiskLedger` (sổ paper trong bộ nhớ, cùng lớp gốc `PaperLedger`) | một sổ riêng cho mỗi lần mô phỏng |
| Khớp / đóng | `PaperBroker.fill`, `close`, `net_pnl`; `PaperMonitor.tick` (hòa vốn, 16:45, cuối tuần, tin HIGH) | `BarBroker` (lớp con) — chỉ thay **cách dò SL / TP trong nến** (mục 6) |

Không chép lại công thức nào (khối lượng, rủi ro, R:R, swap, hạn mức). Đổi một công thức ở GĐ5 → backtest tự đổi theo; báo cáo ghi phiên bản Risk (`risk-policy-…`).

## 3. Hai tầng

**Tầng 1 — chuỗi MarketView lịch sử (chạy một lần cho một bộ dữ liệu).** Với mỗi nến M15 đóng `t` (theo lịch thị trường `market/hours` + ngày lễ): dựng snapshot từ 6 analyst tại `as_of = t` → Quality Gate → Fusion → lưu MarketView (hoặc lý do không có) + các số `decide` cần (ATR14, EMA20 từ output Technical; giá bid đóng nến) vào DB backtest. Kèm **dấu vân tay đầu vào** (băm danh sách id + phiên bản dữ liệu đã đọc) và phiên bản mọi analyst. MarketView **không phụ thuộc** P1 / P7 / P8 → 27 tổ hợp dùng chung một chuỗi.

**Tầng 2 — mô phỏng giao dịch (rẻ, chạy nhiều lần).** Đi lại chuỗi theo thời gian: tại `t` → `PaperMonitor.tick` (quản lý lệnh mở với giá tới `t`) → `decide(MarketView@t, Params)` → `RiskEngine.evaluate` (đồng hồ = `t`) → khớp ở **giá mở nến kế tiếp** → dò SL / TP trong các nến sau. Chạy cho 27 tổ hợp, mốc không lọc, mốc ngẫu nhiên 1.000 lần.

Chạy lại tầng 1 trên cùng dữ liệu → cùng dấu vân tay, cùng chuỗi (test).

## 4. Dữ liệu và DB riêng

- Mọi lệnh backtest đọc **`GT_BACKTEST_DATABASE_URL`**. Thiếu → dừng. **Trùng `DATABASE_URL`** (so sau khi chuẩn hóa: bỏ mật khẩu, so máy / cổng / tên DB) → **từ chối** với thông báo rõ. Không có cờ nào bỏ qua kiểm tra này.
- Schema DB riêng tạo bằng đúng Alembic của backend (cùng bảng → cùng kho đọc).
- Nến lịch sử: `import-csv` (nguồn `CSV`, `backfill=True` → `available_at = close_time`). **H4 / D1** thêm vào `import-csv` (căn theo giờ server, ngày đổi DST dài 23 / 25 giờ — `CandleIngestor` đã kiểm căn khung theo `server_tz`).
- Dữ liệu ngoài: H.15, COT (dùng lại `h15-bu`, `cot-bu`, trỏ DB riêng), lịch kinh tế lịch sử (theo Q1, mục 7). Nguồn giá của tài khoản mô phỏng = nguồn `CSV` của file đã nạp.
- Dữ liệu `SAMPLE` → mọi báo cáo in "không có giá trị đánh giá"; kết luận luôn KHÔNG ĐẠT.

## 5. Cổng lịch sử cho Risk (`RiskGates` cùng giao diện)

| Cổng | Lúc chạy thật | Backtest (tại `t`) |
| --- | --- | --- |
| `accounts.entry_denials` | Safety + khóa người dùng + lệnh cấm làn nhanh | Safety mô phỏng (PAUSED / dừng hẳn do H4 / H6 qua `request_pause`) + **lệnh cấm tin** dựng lại từ lịch lịch sử (cùng cửa sổ thiết kế 17 + chặn 15 phút sau số HIGH) + **spread giãn** (> 3 × trung vị 60 phút, từ spread nến) |
| `accounts.mode` | chế độ tài khoản | **`BACKTEST`** (MOD-03; xem mục 9) |
| `market_views.current` | MarketView mới nhất còn hạn | chuỗi tầng 1, đúng quy tắc hạn / vô hiệu |
| `calendar_health` | sức khỏe nguồn lịch | lịch lịch sử dựng lại được cho ngày đó → khỏe; không dựng được → **không khỏe** (Risk từ chối — an toàn) |
| `broker` | nhịp tim + `spec_at` | `connected = True`, tuổi 0; equity = **equity sổ mô phỏng**; thông số = **thông số broker sớm nhất đã lưu** (KN-05) — giả định, mục 8 |
| `latest_quote` | giây giá thật | giây giá **giả** dựng từ nến (mục 6) |
| `spread_minutes` | spread theo phút 30 ngày (KN-03) | "phút" giả = mỗi nến M15 một dòng, `spread_p95` = spread nến (proxy, mục 8; cách dùng chốt ở Q6) |
| `commission` | phí nhập tay | số theo Q3, ghi trong báo cáo |
| `risk_profile` | hồ sơ hiện hành | **hồ sơ H1–H11 người dùng chốt 16/11**, cố định |
| `trade_book` | sổ cái paper | `RiskLedger` của lần mô phỏng |
| `market_calendar` | lịch thị trường | cùng lịch (tuần + ngày lễ + giờ đặc biệt broker) |

`RiskEngine` lấy giờ từ `clock` → backtest truyền đồng hồ mô phỏng. Nhịp tim / thông số "vừa đổi" (5-C13) không xảy ra trong backtest (một bộ thông số).

## 6. Khớp và đóng theo nến (giá MT5 = giá bid; ask = bid + spread nến × point)

- **Giây giá giả tại `t`** (dùng cho fill, hòa vốn, đóng chủ động): `bid = giá mở nến bắt đầu lúc t`, `ask = bid + spread`, `t = available_at = t`. Không có nến bắt đầu lúc `t` (đóng cửa / hở dữ liệu) → không có giá → **không khớp / không quyết** (`QUOTE_STALE`, an toàn).
- **Vào lệnh:** quyết tại `t` (nến vừa đóng) → `PaperBroker.fill` với giây giá giả của **nến kế tiếp** → BUY vào ở `ask + đệm trượt giá`, SELL ở `bid − đệm` (đúng code paper). Giá chạy quá (rủi ro lúc khớp > rủi ro đã duyệt) → không khớp (`PRICE_MOVED`) — đúng như chạy thật.
- **Dò SL / TP trong một nến** (`BarBroker.check_exits`, thay dò theo giây):
  - BUY: SL chạm khi `low ≤ SL`; giá đóng = `min(SL, open) − đệm trượt giá` (giá mở đã thấp hơn SL = khoảng trống giá → đóng ở giá mở, xấu hơn SL). TP chạm khi `high ≥ TP`; giá đóng = `TP` đúng (không trượt có lợi).
  - SELL: phía ask: SL chạm khi `high + spread ≥ SL`; giá đóng = `max(SL, open + spread) + đệm`. TP chạm khi `low + spread ≤ TP`; giá đóng = `TP`.
  - **Cùng một nến chạm cả SL và TP → SL** (không biết thứ tự trong nến — chọn phía bất lợi, như sổ paper "cùng giây → SL").
  - Nến vào lệnh: chỉ xét từ giá mở trở đi (cả nến vẫn có thể chạm SL / TP — giữ phía bất lợi).
- **Quản lý lệnh** (`PaperMonitor.tick` tại mỗi `t` với giây giá giả = giá đóng nến): hòa vốn (`Manager`, P9) xét tại giá đóng nến — **không** xét trong nến (bảo thủ: dời hòa vốn muộn hơn thật); đóng 16:45 NY (nến 16:30–16:45 đóng đúng 16:45); đóng 30 phút trước cuối tuần / lễ (H8); qua tin HIGH (H7); nhả giữ chỗ hết hạn.
- **Độ trễ:** một nến (quyết sau khi nến đóng, khớp ở giá mở nến kế tiếp). **Khớp một phần:** không mô phỏng — XAUUSD lot nhỏ (0,01–vài lot) coi như khớp đủ; ghi bias.
- **Ký quỹ:** Risk đã kiểm (H9, ký quỹ trống = equity − ký quỹ lệnh mô phỏng).

## 7. Lịch kinh tế lịch sử (điểm mở — Q1, hỏi ở bước 3)

- Lịch đã lưu của hệ thống có `available_at` = lúc tải (từ 11/2026) → không dùng được cho quá khứ. **Không bao giờ** coi "không có bản ghi lịch" là "không có tin".
- Bản ghi dựng lại (nếu Q1 chọn dựng lại) chỉ nằm trong DB backtest, mang cờ `HISTORICAL_RECONSTRUCTED`, giả định `available_at = event_time − 7 ngày` (lịch các cơ quan Mỹ công bố trước nhiều tuần; giả định ghi báo cáo).
- Ngày không dựng được lịch → `calendar_health` không khỏe → Risk chặn cả ngày (an toàn).
- Biến thể "chặn cố định" (protocol-1 mục 2) = chạy thêm, **chỉ để đọc**, không thay bản chính.

## 8. Bias đã biết (báo cáo phải in đủ)

1. **Spread nến MT5** có thể thấp hơn spread thật trung bình (MT5 lưu một con số spread cho cả nến). Đo độ lệch trên đoạn trùng với spread theo phút thật (từ 11/2026) ở bước 2 → Q6.
2. **Đệm trượt giá = p95 spread nến 30 ngày** thay vì p95 spread theo phút — proxy của proxy.
3. **Không có giây giá**: SL / TP trong nến theo high / low, cùng nến → SL; hòa vốn chỉ xét ở giá đóng nến.
4. **Thông số broker hiện hành** (cỡ HĐ, lot, swap, stops level, đòn bẩy) dùng cho cả quá khứ.
5. **Lịch kinh tế dựng lại** (Q1) với giả định `available_at`.
6. **Không có tin (News)** lịch sử → Quality Gate × 0,9 (Q4).
7. **Chỉ số USD** (Macro) có / không tùy Q5.
8. Khớp đủ khối lượng; độ trễ cố định 1 nến; không mô phỏng mất kết nối / Gateway.
9. Dữ liệu **MetaQuotes-Demo** — giá / spread có thể khác sàn thật sau này.

## 9. Chế độ BACKTEST (MOD-03)

- Mọi lần chạy có `run_id`; mọi kết quả (MarketView tầng 1, lệnh mô phỏng, báo cáo) mang nhãn `BACKTEST` + `run_id`, chỉ nằm trong DB backtest.
- `ModeManager` không đổi (LIVE vẫn khóa). Tài khoản mô phỏng có chế độ `BACKTEST` → Risk / chiến lược coi như PAPER về luật vào lệnh (test), nhưng không có tài khoản thật nào được đặt vào `BACKTEST`.

## 10. Walk-forward và khóa đoạn để dành (protocol-1 mục 3–4)

- **Đăng ký** (bảng chỉ-thêm `backtest_registrations` trong DB backtest, có trigger chặn sửa / xóa như các bảng chỉ-thêm khác): khoảng dữ liệu, ranh giới phát triển / để dành (≈ 75 / 25 %, để dành ≥ 6 tháng, đoạn **mới nhất**, cắt ở mốc ngày giao dịch 17:00 NY), lưới 27, số lần thử, dấu vân tay tầng 1, phiên bản mã.
- Lệnh chạy phần phát triển nhận **kho dữ liệu đã cắt** ở ranh giới (đọc sau ranh giới → lỗi), không chỉ "lọc kết quả".
- Walk-forward: học 12 tháng → kiểm 3 tháng, cuốn chiếu; chọn tổ hợp có kỳ vọng / lệnh (R, sau chi phí) cao nhất trên đoạn học (hòa → tổ hợp gần (0,6 / 1,5 / 2) nhất, rồi thứ tự lưới — quy tắc cố định, ghi trước). Tổ hợp ít hơn 30 lệnh trên đoạn học không được chọn; không tổ hợp nào đủ → đoạn kiểm đó không giao dịch (ghi báo cáo).
- **Đoạn để dành:** lệnh riêng + xác nhận; đúng **một** tổ hợp (tổ hợp được chọn nhiều nhất qua các vòng walk-forward; hòa → quy tắc trên); ghi bảng `backtest_holdout_runs` (duy nhất theo đăng ký) **trước** khi chạy → lần hai bị từ chối kể cả khi lần đầu lỗi giữa chừng.

## 11. Thống kê (protocol-1 mục 5–6)

- Lãi / lỗ từng lệnh bằng `Decimal` (từ `net_pnl`); chỉ số tổng hợp bằng `float` (thống kê, không phải tiền).
- R của một lệnh = lãi / lỗ ròng ÷ rủi ro đã duyệt lúc khớp (`risk_at_fill`).
- **Mốc ngẫu nhiên:** cùng số lệnh, cùng tỷ lệ chiều, giờ vào ngẫu nhiên trong cùng cửa sổ phiên P3 (chỉ nến có dữ liệu + Risk cho phép theo luật thời gian), cùng SL / TP theo ATR lúc đó, cùng đóng 16:45 — qua đúng tầng 2; 1.000 lần; hạt giống ghi báo cáo. T4: kỳ vọng / lệnh chiến lược > phân vị 95 %.
- **Deflated Sharpe** (Bailey & López de Prado 2014) trên Sharpe ngày; số lần thử N = 27 + thử thêm; phương sai Sharpe giữa các lần thử từ 27 tổ hợp.
- **PBO** bằng CSCV, 16 khối (Bailey, Borwein, López de Prado, Zhu 2017), ma trận lợi nhuận ngày × 27 tổ hợp.
- **Bootstrap** khoảng tin cậy 95 % kỳ vọng / lệnh: lấy mẫu lại theo **khối ngày giao dịch** (giữ tương quan trong ngày), 10.000 lần, hạt giống ghi lại.
- Test so giá trị tham chiếu tính tay / dựng sẵn (kế hoạch bước 6).

## 12. Báo cáo (BT-03) + kết luận (BT-04, 6-C05)

- File Markdown + HTML trong thư mục người dùng chỉ định + in tóm tắt ra màn hình; đủ mục 9 protocol-1 + mục 8 ở đây; mọi tổ hợp (cả xấu); tổ hợp hiện tại riêng; T1–T8 từng dòng **ĐẠT / KHÔNG ĐẠT** kèm số.
- KHÔNG ĐẠT (hoặc dữ liệu SAMPLE, hoặc thiếu bất kỳ số nào để xét một tiêu chí → tiêu chí đó KHÔNG ĐẠT) → chiến lược giữ "chưa kiểm chứng"; không có hàm nào trong mã GĐ6 đổi trạng thái kiểm chứng của chiến lược (việc đó là quyết định người dùng sau Gate GĐ6) — test khẳng định.

## 13. Hiệu năng (ước tính, đo lại ở bước 4)

~2,5 năm M15 ≈ 60.000 nến mở cửa. Tầng 1 chạy 6 analyst mỗi nến — chậm nhất (ước tính vài giờ, chạy một lần, lưu lại). Tầng 2 không chạy analyst → 27 tổ hợp + 1.000 lần mốc ngẫu nhiên trong thời gian chấp nhận được; nếu chậm → song song theo tổ hợp (không đổi kết quả).

## Nhật ký

- **2026-11-23** — Bản đầu (GĐ6 bước 1). Đọc code thật: `RiskEngine` nhận `clock` + `RiskGates` dạng hàm → dùng lại nguyên Risk; `PaperBroker.fill` đã cộng đệm trượt giá; `RiskLedger` là sổ trong bộ nhớ cùng giao diện; `PaperMonitor` nhận `managers` (hòa vốn / 16:45) → dùng lại; chỉ cần `BarBroker` thay dò SL / TP theo giây bằng theo nến.
