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

## 5a. Dừng / mở lại trong mô phỏng (luật ghi trước, 23/11)

- Risk đề nghị PAUSED (H4: lỗ ngày / tuần / tháng, chuỗi 5 lệnh thua; H6: sụt 5 % từ đỉnh) → tài khoản mô phỏng chặn vào lệnh (`SAFETY_PAUSED:<mã>`).
- **Người dùng mô phỏng mở lại ở mốc ngày giao dịch kế tiếp** (17:00 NY theo hồ sơ) sau lúc dừng; Risk vẫn tự chặn tiếp nếu hạn mức tuần / tháng chưa qua kỳ. H6: lúc mở lại đặt lại đỉnh equity (`drawdown_reset`, như người dùng xác nhận thật). Lý do: dừng vĩnh viễn làm phần còn lại của dữ liệu không đo được gì; mọi lần dừng được **đếm** và in báo cáo (protocol-1 mục 5), và T6 (sụt < 5 %) đã đánh trượt nếu H6 từng chạm.

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
- **Hệ quả cần biết:** đệm trượt giá bị trừ **hai lần** khi chạm SL (lúc vào và lúc thoát) → lỗ thật ở SL lớn hơn rủi ro Risk đã duyệt đúng một đệm × khối lượng × cỡ HĐ (ví dụ tính tay: duyệt 18,80, lỗ 19,20). Cố ý (bảo thủ hơn sổ paper — sổ paper không trừ đệm khi thoát). Khoảng trống giá qua SL → lỗ lớn hơn nữa (test `test_gap_through_stop_closes_at_open_worse`).
- **Swap:** v1 đóng 16:45 NY trước mốc 17:00 → không bao giờ qua đêm → swap luôn 0 trong mô phỏng v1 (công thức swap đã có test ở GĐ5).

## 7. Lịch kinh tế lịch sử (điểm mở — Q1, hỏi ở bước 3)

- Lịch đã lưu của hệ thống có `available_at` = lúc tải (từ 11/2026) → không dùng được cho quá khứ. **Không bao giờ** coi "không có bản ghi lịch" là "không có tin".
- Bản ghi dựng lại (nếu Q1 chọn dựng lại) chỉ nằm trong DB backtest, mang cờ `HISTORICAL_RECONSTRUCTED`, giả định `available_at = event_time − 7 ngày` (lịch các cơ quan Mỹ công bố trước nhiều tuần; giả định ghi báo cáo).
- Ngày không dựng được lịch → `calendar_health` không khỏe → Risk chặn cả ngày (an toàn).
- Biến thể "chặn cố định" (protocol-1 mục 2) = chạy thêm, **chỉ để đọc**, không thay bản chính.

## 8. Bias đã biết (báo cáo phải in đủ)

0. **Bảng ngày lễ** (`market/holidays.py`) chỉ phủ **2024–2027** → nến năm 2023 trở về trước: lịch thị trường "không biết" → Risk chặn hết, quản lý lệnh đóng hết (an toàn, nhưng phí dữ liệu). Muốn dùng 2023: thêm năm 2023 vào bảng ngày lễ (bước 2, cần kiểm từng ngày với lịch CME / sàn).

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
- **Hiện thực (23/11):** Risk đã coi `BACKTEST` như `PAPER` từ GĐ4 (`test_unvalidated_rules_allowed_in_paper_and_backtest`); `StrategyRunner` sửa một dòng: tạo ý định ở `PAPER` **hoặc** `BACKTEST` (trước chỉ `PAPER`). Chế độ đến từ `BacktestAccounts.mode` của tài khoản mô phỏng; hệ thống thật không đổi hành vi.

## 10. Walk-forward và khóa đoạn để dành (protocol-1 mục 3–4)

- **Đăng ký** (bảng chỉ-thêm `backtest_registrations` trong DB backtest, có trigger chặn sửa / xóa như các bảng chỉ-thêm khác): khoảng dữ liệu, ranh giới phát triển / để dành (≈ 75 / 25 %, để dành ≥ 6 tháng, đoạn **mới nhất**, cắt ở mốc ngày giao dịch 17:00 NY), lưới 27, số lần thử, dấu vân tay tầng 1, phiên bản mã.
- Lệnh chạy phần phát triển nhận **kho dữ liệu đã cắt** ở ranh giới (đọc sau ranh giới → lỗi), không chỉ "lọc kết quả".
- Walk-forward: học 12 tháng → kiểm 3 tháng, cuốn chiếu 3 tháng; mọi mốc tính **từ cùng mốc đầu dữ liệu** (vòng k: học [đầu + 3k tháng, đầu + 12 + 3k), kiểm tới đầu + 15 + 3k, ngày 29–31 kẹp về cuối tháng) — không cộng dồn (cộng dồn bị trôi, làm đoạn kiểm hở / chồng: lỗi tìm được khi soát 23/11); đoạn kiểm cuối **cắt ở ranh giới để dành** nếu không đủ 3 tháng (không bỏ dữ liệu phát triển). Phát triển < 15 tháng hoặc tổng < 15 + 6 tháng → không chạy ("không đủ dữ liệu"); chọn tổ hợp có kỳ vọng / lệnh (R, sau chi phí) cao nhất trên đoạn học (hòa → tổ hợp gần (0,6 / 1,5 / 2) nhất, rồi thứ tự lưới — quy tắc cố định, ghi trước). Tổ hợp ít hơn 30 lệnh trên đoạn học không được chọn; không tổ hợp nào đủ → đoạn kiểm đó không giao dịch (ghi báo cáo).
- **Hiện thực walk-forward (23/11, `backtest/walkforward.py`):** mỗi tổ hợp chạy **liền một mạch** trên cả phần phát triển (27 lần mô phỏng); kết quả "học" / "kiểm" của từng vòng = **lát cắt theo giờ mở lệnh** của lần chạy đó (lệnh luôn đóng trong ngày, ranh giới là 17:00 NY → không lệnh nào vắt qua). Ghép lát kiểm của tổ hợp được chọn = ngoài mẫu. Cùng 27 lần chạy cho bảng "mọi tổ hợp", PBO (lợi nhuận ngày từng tổ hợp), DSR (phương sai Sharpe giữa các tổ hợp). Hệ quả cần biết: trạng thái sổ (equity, chuỗi thua, đang dừng) của một tổ hợp ở đầu một đoạn kiểm là trạng thái thật của tổ hợp đó từ đầu phần phát triển — không lộ thông tin tương lai, nhưng khác "một tài khoản đổi tham số mỗi quý"; báo cáo ghi rõ.
- **Chặn đọc đoạn để dành:** `walk_forward` từ chối (`HoldoutLeak`) khi nhận bất kỳ nến / MarketView nào sau ranh giới; bên gọi phải `cut` trước. Dấu vân tay **toàn bộ** dữ liệu (nến + MarketView) phải trùng lúc đăng ký; lưới phải trùng lưới đăng ký.
- **Đoạn để dành:** lệnh riêng + xác nhận; đúng **một** tổ hợp (tổ hợp được chọn nhiều nhất qua các vòng walk-forward; hòa → quy tắc trên); ghi bảng `backtest_holdout_runs` (duy nhất theo đăng ký) **trước** khi chạy → lần hai bị từ chối kể cả khi lần đầu lỗi giữa chừng.

## 11. Thống kê (protocol-1 mục 5–6)

- Lãi / lỗ từng lệnh bằng `Decimal` (từ `net_pnl`); chỉ số tổng hợp bằng `float` (thống kê, không phải tiền).
- R của một lệnh = lãi / lỗ ròng ÷ rủi ro đã duyệt lúc khớp (`risk_at_fill`).
- **Mốc ngẫu nhiên:** cùng số lệnh (**hiệu chỉnh số lần bốc** k để trung vị số lệnh thực khớp ≈ số lệnh chiến lược — bốc đúng n chỉ khớp ~55 % vì va lệnh đang mở / nghỉ 30 phút / 4 lệnh ngày; ≤ 8 vòng × 5 hạt giống riêng), cùng tỷ lệ chiều, giờ vào ngẫu nhiên trong cùng cửa sổ phiên P3 tại mốc có MarketView tầng 1 + có nến để khớp, bỏ V3 / V4 / V6 (hướng bốc thăm), cùng SL / TP / hòa vốn / đóng 16:45 — qua đúng tầng 2 (Risk, chặn tin, hạn mức); 1.000 lần; hạt giống lần i = băm(gốc, i). T4: kỳ vọng / lệnh chiến lược > phân vị 95 %. **Mốc không lọc:** bỏ V3–V6 (cả giờ phiên). **Phiên** (giờ NY lúc mở): Á 18–03, London 03–08, Mỹ 08–17.
- **Deflated Sharpe** (Bailey & López de Prado 2014) trên Sharpe ngày; số lần thử N = 27 + thử thêm; phương sai Sharpe giữa các lần thử từ 27 tổ hợp.
- **PBO** bằng CSCV, 16 khối (Bailey, Borwein, López de Prado, Zhu 2017), ma trận lợi nhuận ngày × 27 tổ hợp.
- **Bootstrap** khoảng tin cậy 95 % kỳ vọng / lệnh: lấy mẫu lại theo **khối ngày giao dịch** (giữ tương quan trong ngày), 10.000 lần, hạt giống ghi lại.
- Test so giá trị tham chiếu tính tay / dựng sẵn (kế hoạch bước 6).

## 12. Báo cáo (BT-03) + kết luận (BT-04, 6-C05)

- File Markdown + HTML trong thư mục người dùng chỉ định + in tóm tắt ra màn hình; đủ mục 9 protocol-1 + mục 8 ở đây; mọi tổ hợp (cả xấu); tổ hợp hiện tại riêng; T1–T8 từng dòng **ĐẠT / KHÔNG ĐẠT** kèm số.
- KHÔNG ĐẠT (hoặc dữ liệu SAMPLE, hoặc thiếu bất kỳ số nào để xét một tiêu chí → tiêu chí đó KHÔNG ĐẠT) → chiến lược giữ "chưa kiểm chứng"; không có hàm nào trong mã GĐ6 đổi trạng thái kiểm chứng của chiến lược (việc đó là quyết định người dùng sau Gate GĐ6) — test khẳng định.

- **Luật chấm ghi trước khi có kết quả (23/11, `backtest/evaluation.py`):** kỳ vọng / lệnh theo **R** sau chi phí; thiếu số → tiêu chí KHÔNG ĐẠT; SAMPLE → cả tám KHÔNG ĐẠT. T2: KTC 95 % bootstrap theo khối **ngày giao dịch ngoài mẫu** (gồm ngày không lệnh), 10.000 lần. T4: mốc ngẫu nhiên trên **đúng khoảng ngoài mẫu**, tổ hợp được chọn nhiều nhất, cùng số lệnh + tỷ lệ mua / bán ngoài mẫu; phải **lớn hơn hẳn** p95 (bằng = không đạt). T5: DSR với Sharpe ngày ngoài mẫu, số quan sát = số ngày ngoài mẫu, phương sai Sharpe = phương sai Sharpe ngày của các tổ hợp trên phần phát triển, số lần thử = lưới + thử thêm; PBO CSCV 16 khối trên lợi nhuận ngày các tổ hợp (phần phát triển). T6: đường equity ngoài mẫu ghép theo ngày (tổ hợp được chọn ở từng đoạn; đoạn không chọn được = 0); đúng 5 % = KHÔNG ĐẠT. T7: để dành chưa chạy = KHÔNG ĐẠT; cần > 0 **và** ≥ ½ kỳ vọng ngoài mẫu. T8: tổng lãi ròng ngoài mẫu ≤ 0 = KHÔNG ĐẠT; mỗi năm và mỗi regime ≤ 70 %.
- **Hiện thực (23/11):** `evaluation.py` (`criteria` thuần + `inputs_from` tính số từ walk-forward), `report.py` (Markdown; HTML + lệnh CLI làm cùng bước 2 / 10 khi có DB riêng). Cảnh báo 6-C04 in trong báo cáo: thử thêm, PBO > 0,2, < 200 lệnh ngoài mẫu, để dành chưa chạy, vòng không chọn được tổ hợp, tổ hợp được chọn đổi giữa các vòng.

## 13. Hiệu năng (ước tính, đo lại ở bước 4)

- **Đo 23/11 (tầng 2):** ~6.000 nến (3 tháng) + ~1.800 MarketView → **~1,5 giây** / lần chạy → ~2,5 năm ≈ 15 giây / tổ hợp; 27 tổ hợp × số vòng walk-forward: vài phút. **Mốc ngẫu nhiên 1.000 lần** theo cách này ≈ 4 giờ → cần làm nhanh (chạy song song, hoặc chỉ mô phỏng lại các ngày có lệnh) — việc của bước 6 phần mốc.

~2,5 năm M15 ≈ 60.000 nến mở cửa. Tầng 1 chạy 6 analyst mỗi nến — chậm nhất (ước tính vài giờ, chạy một lần, lưu lại). Tầng 2 không chạy analyst → 27 tổ hợp + 1.000 lần mốc ngẫu nhiên trong thời gian chấp nhận được; nếu chậm → song song theo tổ hợp (không đổi kết quả).
- **Đo 23/11 (bước 6):** bảng spread dựng một lần / chuỗi nến, equity chỉ tính khi đang dừng → 2,5 năm ít lệnh ~1,8 giây / lần. Mốc ngẫu nhiên (sau hiệu chỉnh, nhiều MarketView giả hơn): 6 tháng × 100 lần ≈ 5 phút với 4 tiến trình → **2,5 năm × 1.000 lần ước ~4 giờ** với 4 tiến trình. Chạy một lần trên máy người dùng; nếu quá lâu → tăng tốc (bỏ qua nhịp không có lệnh / MarketView) trước bước 10, không đổi kết quả (test so trước / sau).
- **Đo 23/11 (bước 7):** sổ paper trong bộ nhớ của GĐ5 (`RiskLedger`) và kho "lần xét" quét toàn bộ lịch sử mỗi lần đọc → chậm theo bình phương (669 lệnh / 22 tháng: 84 giây). Thêm `backtest/fastledger.py` (`FastLedger`: cùng giao diện + ngữ nghĩa giao dịch, đọc qua chỉ mục; equity = nhớ kết quả `replay_equity` của GĐ5, tính lại khi có sự kiện mới) + kho "lần xét" có chỉ mục → **18,5 giây**. Bằng chứng tương đương: bộ test sổ cái + khớp lệnh GĐ5 chạy thêm trên `FastLedger` (40 test), và test so từng lệnh giữa hai sổ trên 40 ngày giá ngẫu nhiên có khoảng trống giá.

## Nhật ký

- **2026-11-23** — Bản đầu (GĐ6 bước 1). Đọc code thật: `RiskEngine` nhận `clock` + `RiskGates` dạng hàm → dùng lại nguyên Risk; `PaperBroker.fill` đã cộng đệm trượt giá; `RiskLedger` là sổ trong bộ nhớ cùng giao diện; `PaperMonitor` nhận `managers` (hòa vốn / 16:45) → dùng lại; chỉ cần `BarBroker` thay dò SL / TP theo giây bằng theo nến.
- **2026-11-23** — Bước 6 + 7 (phần thuần): `backtest/stats.py`, `backtest/protocol.py`. Ghi thêm luật cửa sổ walk-forward tính từ mốc gốc + cắt đoạn kiểm cuối (mục 10).
- **2026-11-23** — Bước 5 (tầng 2): `backtest/simulate.py` — `simulate`, `BarBroker`, `BacktestAccounts`, `HistoricalViews`; `StrategyRunner` nhận `BACKTEST`. Ghi thêm mục 5a (dừng / mở lại), hệ quả đệm trượt giá hai lần, swap v1 = 0, đo hiệu năng, bias 0 (bảng ngày lễ 2024–2027).
- **2026-11-23** — Bước 6 (chỉ số, mốc) + 7 (đăng ký, walk-forward theo lát cắt, chặn đọc đoạn để dành, chạy để dành một lần; migration 0028) + `FastLedger`.
- **2026-11-23** — Bước 8: luật chấm T1–T8 ghi trước (mục 12), `evaluation.py`, `report.py`.
- **2026-11-23** — Bước 9 (soát): equity theo ngày **chỉ ghi ngày giao dịch** (có ≥ 1 nến trong (mốc trước, mốc này]) và ghi nốt mốc tới hết kỳ (trước đây gồm cả thứ Bảy / Chủ nhật lãi 0 → sai Sharpe ngày + số quan sát DSR); lệnh đóng đúng 17:00 NY thuộc ngày sau (như equity). Thước đo toàn quy trình: dữ liệu 2 năm → ngoài mẫu một năm → T8 / T1 gần như chắc trượt kể cả khi có lợi thế (ghi để người dùng quyết độ dài dữ liệu, Q8 kế hoạch).
- **2026-11-23** — Bước 2 (phần mã): `backtest/db.py`, `backtest/data.py`, `backtest/cli.py`. Nạp H4 / D1 làm trong lệnh của backtest (không sửa `import-csv` GĐ1); R1 với H4 / D1 chỉ xét giờ mở nến (nến dài vắt qua giờ nghỉ). DB backtest trên máy người dùng = DB `gold_backtest` trên cùng máy chủ Postgres (khác tên DB → hợp lệ); CI tạo thử.
- **2026-11-23** — Bias 0 xử lý: bảng ngày lễ **riêng** của backtest `BACKTEST_HOLIDAYS` (2020–2027; 2020–2023 nguồn `CME_PATTERN_UNVERIFIED`, phải đối chiếu dữ liệu sàn bằng `data-report --holidays` trước khi chạy); bảng thật không đổi. Lịch backtest = `MarketCalendar(holidays=BACKTEST_HOLIDAYS)` (chưa gồm giờ broker `GT_BROKER_SESSIONS` — thêm khi chạy thật nếu máy người dùng có đặt).
