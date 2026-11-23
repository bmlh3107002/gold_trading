# GĐ6 — Backtest (đặc tả 12): kế hoạch + checklist

> Tạo 2026-11-17. Nguồn sự thật cho mã việc / case: [`docs/giai-doan/GD6-backtest.md`](../giai-doan/GD6-backtest.md). Đặc tả: `docs/huong-dan-chuc-nang/12-van-hanh-kiem-thu.md` (mục Backtest, Mode Manager). Giao thức đánh giá **đã khóa**: [`38-giao-thuc-danh-gia.md`](../thiet-ke/38-giao-thuc-danh-gia.md) (`protocol-1`, T1–T8). Tham số: [`so-tham-so.md`](../thiet-ke/so-tham-so.md). Chiến lược: [`36-chien-luoc-v1.md`](../thiet-ke/36-chien-luoc-v1.md). Xong bước nào tick ở **cả hai** file.
>
> **Trạng thái: NGƯỜI DÙNG ĐÃ DUYỆT 2026-11-17 (Q0 = A). 23/11 người dùng chọn (A): code ngay trên nhánh `gd6-backtest` các phần không cần dữ liệu thật (bước 1 → 5, 6, 7 với dữ liệu tự tạo); bước 2–4 chờ kết quả bước 0.** Q1–Q7 hỏi khi tới bước cần.
>
> **Làm song song (DEC-29, người dùng 2026-11-17).** (1) Người dùng duyệt kế hoạch rồi mới code; (2) code trên **nhánh riêng tách từ `develop`**, **không gộp vào `develop`** tới sau Gate GĐ1 + GĐ2 (code GĐ6 không được làm đổi bản đang kiểm Gate / replay sau NFP); (3) **không đóng GĐ6 trước GĐ5**; việc kiểm trên máy GĐ1/GĐ2 ([`lich-kiem-tren-may.md`](lich-kiem-tren-may.md)) luôn ưu tiên; (4) **máy người dùng không dựng lại** tới sau Gate GĐ1 + GĐ2. **Không có lệnh thật nào:** backtest chỉ tính trên dữ liệu đã qua, không có đường tới Gateway / MT5.

## Nhánh code

- Nhánh **`gd6-backtest`** tách từ `develop` (mốc `0cdae0e`, 17/11) khi bắt đầu code. Không gộp vào `develop` tới sau Gate GĐ1 + GĐ2; nếu `develop` có thêm commit trong lúc đó → gộp `develop` vào nhánh GĐ6 (không ngược lại).
- Migration GĐ6 (nếu cần — ví dụ bảng nhật ký lần chạy backtest) đánh số **sau 0027**. Nếu `develop` có migration mới trước khi gộp → đánh lại số trước khi gộp.
- Mỗi bước: test + ruff (+ `npm run build` nếu sửa giao diện), **kiểm mã thoát thật** (`echo $?` / `PIPESTATUS`), commit (nhắc mã việc) → push nhánh GĐ6 → kiểm CI (job `docker` TimescaleDB thật).

## Hiện trạng code (đọc thật ngày 17/11 trên `develop` `0cdae0e`)

**Có sẵn, dùng lại được:**

- `ingestion/cli.py` **`import-csv`**: đọc file xuất từ MT5 (UTF-8 hoặc UTF-16, tiêu đề `<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>`), bắt buộc `--server-tz` (giờ server broker, IANA), kiểm R1 (> 1 % nến rơi vào giờ đóng cửa → từ chối cả file, gợi ý độ lệch đúng). **`--dry-run` chỉ đọc + kiểm rồi dừng trước khi mở DB** (không đọc `DATABASE_URL`, không ghi gì) → dùng được cho bước 0 mà không đụng DB đang chạy. Khung chỉ nhận **M1–H1**; **H4 / D1 chưa hỗ trợ** qua CSV.
- `ingestion/candles.py` `CandleIngestor`: cửa nạp duy nhất; `backfill=True` → `available_at = close_time` (cờ `BACKFILL`), giữ `spread_points` từng nến. Đúng thứ backtest cần cho point-in-time của nến.
- `strategy/trend_m15.py`: `decide(Inputs, Params)` và `Manager` là **hàm / lớp thuần** (không đọc DB, không gửi gì) → backtest gọi thẳng; lưới 27 tổ hợp chỉ là đổi `min_confidence` (P1), `sl_atr` (P7), `tp_r` (P8) trong `Params`.
- `intelligence/` (snapshot → Quality Gate → Fusion), `analysts/` (6 analyst có phiên bản: `technical-1.6.0`, `regime-1.2.0`, `event-1.0.0`, `macro-1.1.0`, `positioning-1.0.0`, `news-1.1.0`): chạy được ở thời điểm `as_of` bất kỳ với kho đọc point-in-time.
- `orchestrator/replay.py`: replay **chỉ đọc, trong bộ nhớ**, so sự kiện / làn nhanh / technical với lúc chạy thật (Gate GĐ2). Là khung tốt cho BT-01 nhưng **chỉ so khớp** — chưa chạy chuỗi analyst → Fusion → chiến lược → Risk → khớp lệnh.
- `risk/engine.py`, `risk/sizing.py`, `risk/periods.py`, `risk/book.py`: công thức khối lượng / rủi ro (gồm spread + đệm trượt giá + phí + swap), R:R sau chi phí, hạn mức ngày / tuần / tháng, chuỗi thua, heat, H6–H11 — đều bằng `Decimal`, đã có test tính tay.
- `risk/feasibility.py`: cùng công thức Risk, báo cáo khả thi (vốn tối thiểu cho 0,01 lot).
- `ingestion/cli.py` `h15-bu` (mặc định 400 ngày, chỉnh `--days`) và `cot-bu` (mặc định 4 năm): nạp bù lịch sử Macro / Positioning.

**Chưa có / không dùng thẳng được cho 2 năm quá khứ:**

- `modes/manager.py`: có giá trị `BACKTEST` trong `TradingMode` nhưng **không nối với gì** (MOD-03). `performance/`, `position/`: trống.
- `strategy/runner.py` `StrategyRunner` và `risk/paper.py` `PaperBroker` / `PaperMonitor`: gắn với **cổng thật lúc này** (`AccountRegistry`, `MarketViewStore`, nhịp tim Gateway, giây giá `QuoteSecond`, `utcnow`). Không chạy ở thời điểm quá khứ được.
- Risk tự đọc: equity từ nhịp tim, `spec_at` (thông số broker — chỉ có từ khi KN-05 chạy), **đệm trượt giá + ngưỡng spread = p95 spread theo phút 30 ngày** (`market/quote_minutes.py` — chỉ có từ 11/2026), phí / lot nhập tay. → Backtest phải cấp **cổng lịch sử cùng giao diện**; với 2 năm trước, spread theo phút **không có** → phải dùng spread của nến M15 làm proxy (bias, ghi báo cáo).
- Khớp paper theo **giây giá**; 2 năm trước không có giây giá → backtest khớp theo nến M15 (protocol-1: khớp ở nến **sau** nến ra tín hiệu).
- **Technical cần H1 / H4 / D1** (MTF, TEC-09): thiếu → `NOT_EVALUATED` → mất lọc `MTF_CONFLICT` của Fusion → backtest hành xử **khác** lúc chạy thật. Phải có nến H1 / H4 / D1 lịch sử, và `import-csv` phải nhận H4 / D1 (căn theo giờ server, ING-14).
- **Lịch kinh tế (Event — nhóm bắt buộc)**: bản ghi lịch có `available_at` = lúc tải (11/2026). Replay 2 năm trước sẽ **không thấy sự kiện nào** → Event báo "không có tin" → backtest vào lệnh ngay trước NFP / CPI / FOMC — **lạc quan sai, nguy hiểm**. FOMC: trang lịch họp có các năm trước; BLS: chép tay (bảng 2026); DOL: theo quy tắc (sinh lại được); BEA / Census: file lịch hiện hành. → **Điểm còn mở, Q1.**
- **News (nhóm tùy chọn)**: tin RSS không có lịch sử → trong backtest News luôn "thiếu" → Quality Gate nhân độ tin cậy × 0,9 → khác lúc chạy thật (ảnh hưởng ngưỡng P1 = 0,6). → Q4.
- **Macro (tùy chọn)**: lợi suất thực 10 năm (H.15) bắt buộc trong Macro — cần ≥ 2 năm + phần khởi động → `h15-bu --days` lớn hơn. Chỉ số USD tự tính cần **6 cặp tiền M15** của chính sàn (tùy chọn; thiếu → hạ trần confidence Macro). → Q5.
- Thống kê (Deflated Sharpe, PBO / CSCV, bootstrap theo khối, mốc ngẫu nhiên): **chưa có gì**.

## Ý tưởng chính

- **Chạy đúng mã đang dùng, không viết lại luật:** backtest gọi đúng analyst / Quality Gate / Fusion / `decide` / `Manager` / công thức Risk của phiên bản hiện hành; chỉ thay **nguồn đọc** (kho point-in-time trên dữ liệu lịch sử) và **nơi khớp** (khớp theo nến). Báo cáo ghi phiên bản mọi thành phần.
- **Không đụng DB đang chạy:** backtest dùng **DB riêng** (`GT_BACKTEST_DATABASE_URL`); lệnh backtest **từ chối chạy** nếu URL này trùng `DATABASE_URL` của hệ thống đang chạy, hoặc thiếu. Nến lịch sử nạp vào DB riêng bằng cùng `CandleIngestor` (nguồn `CSV`, `backfill`).
- **Point-in-time tuyệt đối:** tại mỗi nến M15 đóng `t`, chỉ đọc dữ liệu `available_at ≤ t`. 6-C01 kiểm bằng test: thêm dữ liệu sau `t` → mọi kết quả tới `t` giống hệt (so băm).
- **Tách hai tầng cho nhanh và đúng:** tầng 1 tính **chuỗi MarketView lịch sử một lần** (không phụ thuộc P1 / P7 / P8) và lưu vào DB riêng; tầng 2 mô phỏng 27 tổ hợp + mốc ngẫu nhiên 1.000 lần trên chuỗi đó (nhanh). Tầng 1 có dấu vân tay dữ liệu đầu vào → chạy lại ra cùng kết quả.
- **Mặc định an toàn khi thiếu:** thiếu nến / thiếu lịch / nến bị Quality Gate loại → **không giao dịch** đoạn đó, ghi vào báo cáo (6-C03). Không nội suy, không đoán.
- **Khớp theo nến — luôn chọn phía bất lợi:** vào lệnh ở giá mở nến kế tiếp (BUY = ask = mở + spread; SELL = bid); SL / TP trong nến theo high / low của đúng phía giá (BUY đóng ở bid; SELL đóng ở ask = giá + spread); cùng một nến chạm cả SL và TP → coi là **SL** (như sổ paper); khoảng trống giá qua SL → đóng ở giá mở nến (xấu hơn SL); TP không trượt có lợi.
- **Đoạn để dành bị khóa bằng mã:** khoảng thời gian để dành tính từ dữ liệu lúc đăng ký và ghi vào nhật ký chỉ-thêm; mọi lệnh chạy phần phát triển **cắt dữ liệu trước** đoạn để dành; chạy đoạn để dành cần cờ riêng + ghi nhật ký; lần thứ hai bị từ chối.
- **Ngoài phạm vi GĐ6:** đổi luật analyst / Fusion / chiến lược (đổi = phiên bản mới, quyết riêng); dò tham số ngoài lưới 27; hiệu chỉnh xác suất (GĐ7); paper dài hạn (GĐ8).

## Thứ tự làm (mỗi bước: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick → commit → push nhánh GĐ6 → kiểm CI)

### Bước 0 — VIỆC ĐẦU TIÊN, KIỂM TRÊN MÁY: MT5 có bao nhiêu năm nến? (chỉ xuất file, KHÔNG nạp)
- [ ] 0a. Xuất **XAUUSD M15** từ MT5 ra file (hướng dẫn ở mục "Kiểm trên máy — bước 0"). Ghi: ngày nến đầu, ngày nến cuối, số nến. **Cần ≥ 2 năm** (tối thiểu tuyệt đối 21 tháng = 12 tháng học + 3 tháng kiểm + 6 tháng để dành; dưới mức đó protocol-1 không chạy được).
- [ ] 0b. Xuất **XAUUSD H1, H4, D1** (cho Technical MTF). Ghi ngày đầu / cuối / số nến.
- [ ] 0c. Kiểm file M15 và H1 **chỉ đọc** bằng `import-csv --dry-run` (không mở DB, không ghi gì): số nến đọc được, số dòng lỗi, khoảng thời gian UTC, kiểm múi giờ R1 đạt.
- [ ] 0d. Người phát triển ghi kết quả vào nhật ký; < 21 tháng → dừng, hỏi người dùng (không chạy protocol-1 với dữ liệu ngắn hơn).
- Không đụng tới: nạp vào DB đang chạy, dựng lại, khởi động lại MT5 / Gateway, đổi cài đặt MT5. Không làm trong khung băng đỏ, tối thứ Sáu / cuối tuần.

### Bước 1 — Chuẩn bị + thiết kế (không đổi hành vi)
- [x] (23/11) Tạo nhánh `gd6-backtest` từ `develop` (`187c50f`); chạy test gốc (backend, mt5_gateway, frontend) + ruff, ghi số làm mốc. *(Mốc: backend 2841 passed, 3 skipped; mt5_gateway 206; frontend 150, build đạt; ruff sạch. Trước đó sửa trên `develop` test GĐ1 `test_cli_dry_run` (Census) phụ thuộc ngày thật — CI `develop` đỏ từ 21/11.)*
- [x] (23/11) Thiết kế `docs/thiet-ke/39-backtest.md`: hai tầng; DB riêng + chốt chặn trùng URL; cổng lịch sử cho Risk (equity mô phỏng, thông số broker, spread / đệm trượt giá từ nến, phí, sổ lệnh mô phỏng); luật khớp theo nến; danh sách **bias đã biết** (spread nến MT5, không có giây giá, thông số broker hiện hành dùng cho quá khứ, lịch kinh tế dựng lại, không có News, khớp đủ khối lượng); đơn vị + `Decimal`. Viết **trước** khi code bước 2–8.

### Bước 2 — Dữ liệu giá lịch sử vào DB riêng (BT-01 phần dữ liệu; 6-C03 phần dữ liệu)
- [ ] `import-csv` nhận **H4 / D1** (căn theo giờ server, ngày đổi DST 23 / 25 giờ — ING-14 đã có trong `CandleIngestor`); test DST, nến lệch căn.
- [ ] Lệnh backtest dùng `GT_BACKTEST_DATABASE_URL`; **từ chối** khi thiếu hoặc trùng `DATABASE_URL` (test). Khởi tạo schema DB riêng bằng Alembic.
- [ ] Báo cáo dữ liệu (chỉ đọc): khoảng thời gian, chỗ hở trong giờ mở cửa (theo `market/hours` + ngày lễ), nến bị cách ly, nến spike / đóng băng, phân bố spread theo phiên. Chỗ hở → danh sách cho báo cáo GĐ6.
- [ ] **Đo độ lệch spread nến so với thật:** trên đoạn trùng (từ 11/2026, khi đã có spread theo phút thật) so spread cột `<SPREAD>` của nến M15 với trung vị / p95 spread theo phút cùng nến. Kết quả quyết Q6 (cách dùng spread lịch sử).

### Bước 3 — Dữ liệu ngoài lịch sử (lịch kinh tế theo Q1; Macro, Positioning)
- [ ] Lịch kinh tế lịch sử theo lựa chọn Q1. Bản ghi dựng lại mang cờ `HISTORICAL_RECONSTRUCTED` + giả định `available_at` (ví dụ: lịch công bố trước ≥ 7 ngày) ghi rõ trong thiết kế 39; **không** trộn vào bảng lịch của hệ thống đang chạy (chỉ ở DB riêng).
- [ ] H.15 ≥ 2 năm + phần khởi động (60 quan sát), COT ≥ 2 năm + 52 tuần, vào DB riêng (dùng lại `h15-bu` / `cot-bu` trỏ DB riêng). Revision: chỉ dùng bản đã biết tại `t`.
- [ ] Test: ngày có NFP / CPI / FOMC trong dữ liệu dựng lại → Event ra cửa sổ tin đúng giờ (đổi giờ mùa hè / đông); ngày không có lịch dựng lại được → **chặn cả ngày** (an toàn), không coi là "không có tin".

### Bước 4 — Tầng 1: chuỗi MarketView lịch sử (BT-01; 6-C01, 6-C02)
- [ ] Vòng lặp theo từng nến M15 đóng: chạy 6 analyst (đúng phiên bản hiện hành) với kho point-in-time tại `t` → snapshot → Quality Gate → Fusion → lưu MarketView + các số Technical cần cho `decide` (ATR14, EMA20, giá) vào DB riêng, kèm dấu vân tay đầu vào.
- [ ] Ghi cả lý do **không có** MarketView (Quality Gate loại, thiếu nến, thiếu lịch) để báo cáo đếm.
- [ ] **6-C01:** chạy tới `T` → băm kết quả; thêm dữ liệu sau `T` (nến, lịch, H.15, COT, cả bản sửa số đến muộn) → chạy lại tới `T` → băm giống hệt. Đột biến: cho một analyst đọc `available_at ≤ t + 15 phút` → test phải đỏ.
- [ ] **6-C02:** tuần đổi giờ Mỹ trước châu Âu (3 tuần lệch DST), cuối tuần, ngày lễ (Giáng sinh, Năm mới, Lễ Tạ ơn đóng sớm): không có nến "ma", không vào lệnh khi thị trường đóng, giờ New York của chiến lược đúng.
- [ ] Đối chiếu: trên đoạn trùng với lúc chạy thật (từ 11/2026), MarketView tầng 1 so với MarketView đã lưu của hệ thống thật (cùng phiên bản) — khác nhau phải giải thích được (ví dụ News).

### Bước 5 — Tầng 2: mô phỏng giao dịch + chi phí (BT-02; MOD-03)
- [x] (23/11) Cổng lịch sử cho Risk (cùng giao diện cổng thật, test riêng): equity = sổ lệnh mô phỏng; thông số broker = theo Q / thiết kế 39; spread lúc vào = theo Q6; đệm trượt giá + ngưỡng spread = p95 spread 30 ngày trước `t` (từ nguồn spread lịch sử); phí / lot = theo Q3; hồ sơ rủi ro H1–H11 đúng như đã chốt.
- [x] (23/11) Gọi **đúng** `decide` + công thức Risk (khối lượng, R:R sau chi phí, hạn mức, chuỗi thua, heat, H6 dừng hẳn, H7 qua tin, H8 cuối tuần, H9 đòn bẩy, ký quỹ) — không chép công thức.
- [x] (23/11) Khớp + quản lý lệnh theo nến (mục "Ý tưởng chính"): vào ở nến sau; SL / TP / hòa vốn (`Manager`) / đóng 16:45 NY / đóng trước cuối tuần; swap theo thông số; độ trễ = 1 nến; khớp đủ khối lượng (bias ghi rõ).
- [~] (23/11 phần mô phỏng) MOD-03: chế độ `BACKTEST` — mọi kết quả mang nhãn BACKTEST, không bao giờ ghi vào sổ paper / bảng của hệ thống đang chạy; dữ liệu `SAMPLE` → báo cáo "không có giá trị đánh giá".
- [x] (23/11) Test **tính tay**: vài lệnh mẫu (BUY / SELL, chạm SL, chạm TP, cùng nến chạm cả hai → SL, khoảng trống giá qua SL, hòa vốn, đóng 16:45, đóng trước cuối tuần, swap thứ Tư ×3) — lãi / lỗ sau chi phí khớp số tính tay; dưới lot tối thiểu → không vào (đếm vào báo cáo).

*(23/11: `backtest/simulate.py` + `tests/test_backtest_simulate.py` 33 test — TP +35,20 / SL −19,20 / khoảng trống −31,20 / hòa vốn 0,00 / đóng 16:45 −1,20 / SELL +35,60 / cuối tuần thứ Sáu 16:30 / tuần lệch DST / thiếu nến / lịch không khỏe / thiếu nền spread / vốn dưới lot tối thiểu / dừng–mở lại / point-in-time spread / không import Gateway–mạng–DB thật. Swap ×3: không xảy ra với v1 (đóng 16:45). Dùng lại nguyên `StrategyRunner`, `RiskEngine`, `RiskLedger`, `PaperBroker`, `PaperMonitor`; mới: `BarBroker`, cổng lịch sử. Còn của MOD-03: nhãn `run_id` + DB backtest — cùng bước 2 / 8.)*

### Bước 6 — Thống kê + mốc so sánh (protocol-1 mục 5–6)
- [x] (23/11) Chỉ số mục 5 (sau chi phí, mức 0,25 %): số lệnh, tỷ lệ thắng, kỳ vọng / lệnh (R + USD), hệ số lợi nhuận, sụt giảm lớn nhất, chuỗi thua dài nhất, số lần chạm H6 / H4, Sharpe theo ngày, thời gian giữ; chia theo regime / phiên / năm / chiều. *(`backtest/metrics.py`: `trades_of`, `summarize` — R = lãi ròng ÷ rủi ro lúc khớp; sụt giảm theo equity chốt mỗi 17:00 NY; phiên theo giờ NY lúc mở: Á 18–03, London 03–08, Mỹ 08–17.)*
- [x] (23/11) Mốc ngẫu nhiên 1.000 lần (cùng giờ phiên, cùng số lệnh, cùng tỷ lệ chiều, cùng SL / TP / đóng 16:45; hạt giống ngẫu nhiên ghi lại); mốc không lọc (bỏ V3–V6); tham chiếu 0 và mua – giữ. *(`backtest/baselines.py`: mốc ngẫu nhiên qua đúng tầng 2, bỏ V3 / V4 / V6, hạt giống theo (gốc, lần), chạy song song cho kết quả giống hệt tuần tự; **hiệu chỉnh số lần bốc** để số lệnh thực khớp ≈ số lệnh chiến lược; mốc không lọc; mua – giữ. `tests/test_backtest_metrics.py` 12 test.)*
- [x] (23/11) Deflated Sharpe Ratio (Bailey & López de Prado 2014), PBO bằng CSCV 16 khối (Bailey và cộng sự 2017), bootstrap khoảng tin cậy 95 % theo khối ngày. *(`backtest/stats.py`, thư viện chuẩn, không numpy.)*
- [x] (23/11) Test so **giá trị tham chiếu**: ví dụ số trong bài báo gốc (DSR), PBO trên dữ liệu dựng sẵn biết đáp án (chiến lược ngẫu nhiên → PBO ≈ 0,5), bootstrap trên chuỗi biết trung bình; Sharpe / sụt giảm tính tay trên chuỗi nhỏ. *(`tests/test_backtest_stats.py` 12 test: DSR ví dụ bài báo = **0,9004** khớp; PBO ngẫu nhiên ≈ 0,5, có lợi thế thật < 0,05, quá khớp > 0,4; soát riêng: PBO viết lại thô bằng `statistics` khớp tuyệt đối trên 6 bộ ngẫu nhiên. Chỉ số mục 5 dạng hàm thuần đã có; phần chia theo regime / phiên / năm / chiều, mốc ngẫu nhiên và mốc không lọc cần bộ mô phỏng → làm cùng bước 5.)*

### Bước 7 — Walk-forward + khóa đoạn để dành (protocol-1 mục 3–4; 6-C04)
- [x] (23/11) Đăng ký lần chạy: khoảng dữ liệu, ranh giới phát triển / để dành (≈ 75 / 25 %, để dành ≥ 6 tháng, là đoạn **mới nhất**), lưới 27 tổ hợp, số lần thử — ghi vào nhật ký chỉ-thêm (DB riêng) trước khi chạy.
- [x] (23/11) Walk-forward: học 12 tháng → kiểm 3 tháng, cuốn chiếu; mỗi vòng chọn tổ hợp tốt nhất theo kỳ vọng / lệnh sau chi phí trên đoạn học; ghép các đoạn kiểm = ngoài mẫu. *(`backtest/protocol.py`: lưới 27 khóa thứ tự, `make_split` (để dành ≈ 25 %, ≥ 6 tháng, đoạn mới nhất, mốc 17:00 NY), `select_combo` / `holdout_combo` (≥ 30 lệnh học; hòa → gần tổ hợp hiện tại, rồi thứ tự lưới). Còn: chạy thật trên bộ mô phỏng — sau bước 5.)*
- [x] (23/11) **6-C04:** mã không cho tối ưu trên toàn bộ dữ liệu; tổ hợp ngoài lưới → bị từ chối hoặc phải ghi + cộng vào số lần thử (cảnh báo trong báo cáo); dữ liệu đoạn để dành **không đọc được** ở mọi lệnh chạy phần phát triển (test: cố đọc → lỗi).
- [x] (23/11) Chạy đoạn để dành: cờ riêng, đúng **một** tổ hợp đã chọn, một lần; lần hai → từ chối (test).

*(23/11: `backtest/registry.py` (bảng chỉ-thêm `backtest_registrations` / `backtest_trials` / `backtest_holdout_runs`, migration **0028**, trigger chặn sửa / xóa; `n_trials` = lưới + lần thử thêm; `claim_holdout` ghi **trước** khi chạy), `backtest/walkforward.py` (`cut`, `walk_forward` theo lát cắt của 27 lần chạy liền mạch, `HoldoutLeak`, dấu vân tay dữ liệu, `run_holdout`). `tests/test_backtest_walkforward.py` 9 test: kho bộ nhớ + SQLite, không ghi đè, lần thử thêm, để dành một lần kể cả khi lần đầu lỗi giữa chừng, lọt nến / MarketView sau ranh giới → từ chối, dữ liệu đổi → từ chối, lưới khác → từ chối, lát học / kiểm đúng cửa sổ. Lệnh CLI + DB riêng (`GT_BACKTEST_DATABASE_URL`, từ chối khi trùng DB thật) làm cùng bước 2 / 8.)*

### Bước 8 — Báo cáo + kết luận (BT-03, BT-04; 6-C05)
- [~] (23/11 phần Markdown xong; HTML + lệnh CLI cùng bước 2 / 10) Báo cáo (file HTML / Markdown + lệnh CLI chỉ đọc) đủ mục 9 protocol-1: giả định chi phí, khoảng dữ liệu + chỗ thiếu, phiên bản mọi thành phần, số lần thử thật, bias còn lại, kết quả **mọi** tổ hợp (tổ hợp hiện tại 0,6 / 1,5 / 2 riêng), kết luận **ĐẠT / KHÔNG ĐẠT** theo từng T1–T8. Không có chữ "xác suất thắng" / "độ tin cậy dự báo".
- [x] (23/11) **6-C05:** báo cáo KHÔNG ĐẠT → chiến lược giữ trạng thái **chưa kiểm chứng** (cờ `UNVALIDATED_RULES` giữ nguyên), không có đường nào đánh dấu "đã kiểm chứng" từ báo cáo không đạt (test); ghi rõ "quay lại GĐ5, không sang GĐ8".
- [x] (23/11) Dữ liệu `SAMPLE` → báo cáo in "không có giá trị đánh giá", kết luận luôn KHÔNG ĐẠT.

*(23/11: `backtest/evaluation.py` + `backtest/report.py`; `tests/test_backtest_report.py` 35 test: đạt cả tám với số tính tay; từng ngưỡng trượt đúng ở mép (199 lệnh, cận dưới 0, bằng p95, DSR 0,9499, PBO 0,2001, sụt đúng 5 %, để dành 0,245R…); SAMPLE không bao giờ đạt; báo cáo đủ mục, cấm chữ "xác suất thắng"; bất biến tổng lãi / lỗ ngày ngoài mẫu = tổng lãi / lỗ lệnh ngoài mẫu; 6-C05: mã `backtest/` không đụng `UNVALIDATED_RULES` / chế độ / Quality Gate. Soát đột biến 12 phép so sánh ngưỡng: lọt 1 (T7 "> 0") → thêm test → bắt được.)*

### Bước 9 — Soát riêng (kịch bản nhắm chỗ dễ sai)
- [ ] Dữ liệu tổng hợp **đi ngẫu nhiên** (không có lợi thế) → kết luận phải KHÔNG ĐẠT (T4 / T5); dữ liệu tổng hợp **cài sẵn lợi thế** biết trước → hệ thống phải phát hiện. Hai kịch bản này là "thước đo" cho cả bộ máy.
- [ ] Rò rỉ: đảo thứ tự / thêm dữ liệu tương lai / bản sửa số đến muộn → kết quả quá khứ không đổi.
- [ ] Công thức lãi / lỗ: viết lại độc lập (phân số chính xác) cho hàng nghìn lệnh ngẫu nhiên → lệch 0.
- [ ] Postgres + TimescaleDB qua CI.

### Bước 10 — Chạy thật + Gate GĐ6 (sau Gate GĐ1 + GĐ2, người dùng chọn lịch)
- [ ] Gộp nhánh GĐ6 vào `develop` (sau Gate GĐ1 + GĐ2) → một lần dựng lại cho tất cả (theo lịch kiểm).
- [ ] Trên máy người dùng: nạp file đã xuất ở bước 0 vào **DB riêng** của backtest; chạy tầng 1, rồi phần phát triển (walk-forward) → gửi báo cáo.
- [ ] Người dùng xem phần phát triển → nếu muốn đi tiếp: chạy đoạn để dành **một lần**.
- [ ] Báo cáo cuối GĐ6 → **người dùng duyệt** (Gate GĐ6). Không đóng GĐ6 trước GĐ5 (DEC-29).

## Case bắt buộc (GĐ6)

| Mã | Tình huống | Làm ở | Cách kiểm |
| --- | --- | --- | --- |
| 6-C01 | Rò rỉ tương lai | Bước 4 (+ soát bước 9) | Thêm dữ liệu sau `T` (nến, lịch, số liệu, bản sửa) → băm kết quả tới `T` giống hệt; đột biến đọc lố 15 phút → test đỏ |
| 6-C02 | Gap cuối tuần, ngày lễ, tuần lệch DST | Bước 2 (H4 / D1), 4, 5 | Không nến ma, không lệnh khi đóng cửa, đóng trước cuối tuần đúng giờ, giờ NY đúng trong 3 tuần lệch DST; khoảng trống giá qua SL đóng ở giá mở (xấu hơn) |
| 6-C03 | Thiếu dữ liệu một đoạn | Bước 2, 3, 4 | Đoạn hở / bị loại → không vào lệnh; lệnh đang mở xử lý theo nến kế tiếp có dữ liệu (giá xấu hơn nếu có khoảng trống); mọi đoạn thiếu liệt kê trong báo cáo |
| 6-C04 | Quá khớp | Bước 7 | Không tối ưu trên toàn bộ dữ liệu; đoạn để dành không đọc được khi phát triển, chạy đúng một lần; thử ngoài lưới → cộng số lần thử + cảnh báo; DSR + PBO trong báo cáo |
| 6-C05 | Kết quả không đạt tiêu chí | Bước 8 | KHÔNG ĐẠT → chiến lược vẫn "chưa kiểm chứng", không có đường đánh dấu đã kiểm chứng; báo cáo ghi "quay lại GĐ5, không sang GĐ8" |

## Câu hỏi cần người dùng trả lời (hỏi lần lượt, mỗi lần một câu)

| Mã | Câu hỏi | Lựa chọn (khuyến nghị in đậm) | Cần cho | Trả lời |
| --- | --- | --- | --- | --- |
| Q0 | Duyệt kế hoạch này? | **(A) Duyệt cả bản** · (B) Duyệt, sửa vài điểm · (C) Chưa duyệt | Bắt đầu | **Chốt 17/11: (A) duyệt cả bản** |
| Q1 | **Lịch kinh tế lịch sử 2 năm** (điểm còn mở của protocol-1). Lịch hệ thống đã lưu chỉ có từ 11/2026 | **(A) Dựng lại lịch quá khứ từ trang chính thức** (FOMC: trang lịch họp các năm trước; DOL: sinh lại theo quy tắc; BEA / Census: lịch lưu trữ; BLS: bạn chép tay 2–3 bảng lịch năm như lần trước) làm bản chính, **và** chạy thêm biến thể "chặn cố định 08:30 / 10:00 / 14:00 NY mọi ngày làm việc" để so (đúng protocol-1 mục 2) · (B) Chỉ chặn cố định (đơn giản, chặn nhiều hơn thật, ít lệnh hơn) · (C) Chờ hệ thống tự lưu đủ 2 năm lịch (backtest lùi ~2 năm) | Bước 3 | |
| Q2 | Vốn ban đầu dùng trong backtest (vốn nhỏ → 0,01 lot đã vượt 0,25 % → Risk từ chối mọi lệnh) | **(A) Số vốn bạn dự định dùng khi chạy thật** · (B) Equity tài khoản demo hiện tại · (C) 10.000 USD (số ví dụ) | Bước 5 | |
| Q3 | Phí / lot trong backtest (MetaQuotes-Demo thường không thu phí; sàn thật có thể thu) | **(A) Phí của sàn bạn định dùng thật** (nếu chưa chọn sàn: chạy với 0 và ghi rõ là giả định lạc quan) · (B) Luôn 0 · (C) 0 làm bản chính, thêm một dòng "nếu phí 7 USD / lot" chỉ để đọc (không dùng làm tiêu chí) | Bước 5 | |
| Q4 | Tin tức (News) không có lịch sử → trong backtest luôn "thiếu" → độ tin cậy × 0,9, khác lúc chạy thật | **(A) Giữ nguyên luật hiện hành** (× 0,9), ghi là bias; báo thêm số MarketView rơi đúng quanh ngưỡng 0,6 · (B) Bỏ × 0,9 riêng trong backtest (= đổi phiên bản Quality Gate, cần quyết định riêng — không khuyến nghị) | Bước 4 | |
| Q5 | Chỉ số USD (Macro, tùy chọn) cần nến M15 của 6 cặp tiền 2 năm | **(A) Xuất thêm 6 cặp** từ MT5 (cùng cách bước 0) · (B) Bỏ, Macro chạy không có chỉ số USD (hạ trần confidence), ghi bias | Bước 3 | |
| Q6 | Spread lịch sử: cột `<SPREAD>` của nến MT5 có thể thấp hơn spread thật (hỏi **sau** khi có số đo ở bước 2) | (A) Dùng spread nến, ghi bias · (B) Dùng spread nến nhưng nâng lên theo tỷ lệ đo được trên đoạn trùng · (C) Dùng mức xấu hơn của hai cách — khuyến nghị chọn sau khi có số đo | Bước 2 / 5 | |
| Q7 | Chạy backtest thật ở đâu | **(A) Trên máy bạn**, container riêng + DB riêng, sau Gate GĐ1 + GĐ2 (dữ liệu chính sàn, không gửi file đi đâu; người phát triển không thấy đoạn để dành trước) · (B) Bạn gửi file cho người phát triển chạy trong máy ảo phát triển | Bước 10 | |

## Kiểm trên máy người dùng — bước 0 (xuất nến từ MT5, KHÔNG nạp)

> Chỉ **xuất file** và **đọc thử**. Không nạp vào cơ sở dữ liệu, không dựng lại, không khởi động lại MT5 hay Gateway, không đổi cài đặt MT5 (đang đếm 5 ngày cho Gate GĐ1). Không làm trong khung băng đỏ, tối thứ Sáu / cuối tuần. Không dán mật khẩu / token / khóa API vào chat.

**1. Tạo thư mục chứa file** (PowerShell):

```powershell
New-Item -ItemType Directory -Force C:\gold-backtest
```

**2. Xuất XAUUSD M15 trong MT5** (cửa sổ MT5 đang chạy, MetaQuotes-Demo; **không đóng / mở lại MT5**):

1. Menu **Xem (View) → Ký hiệu (Symbols)** (hoặc `Ctrl+U`).
2. Thẻ **Thanh (Bars)**. Chọn mã **XAUUSD**, khung **M15**, từ ngày **2023.01.01** tới **hôm nay**. Bấm **Yêu cầu (Request)** — MT5 tải lịch sử từ máy chủ (có thể mất 1–2 phút).
3. Ghi lại: **ngày giờ nến đầu tiên**, **ngày giờ nến cuối cùng**, **số thanh** MT5 hiện (nếu có). Nếu số thanh **tròn đúng** 100.000 hoặc 50.000 → có thể bị giới hạn bởi cài đặt, **không tự đổi cài đặt**, chỉ báo lại.
4. Bấm **Xuất thanh (Export Bars)** → lưu thành `C:\gold-backtest\XAUUSD_M15.csv`.

**3. Làm lại bước 2 cho H1, H4, D1** (từ **2022.01.01**) → lưu `XAUUSD_H1.csv`, `XAUUSD_H4.csv`, `XAUUSD_D1.csv` trong cùng thư mục. Ghi ngày đầu / cuối / số thanh mỗi khung.

**4. Đọc thử file (chỉ đọc, không ghi gì vào cơ sở dữ liệu)** — trong PowerShell tại `C:\gold-trading`, gõ từng lệnh một:

```powershell
docker compose cp ..\gold-backtest\XAUUSD_M15.csv backend:/tmp/bt_m15.csv
```

```powershell
docker compose exec backend python -m gold_trading.ingestion.cli import-csv /tmp/bt_m15.csv --server-tz Europe/Athens --dry-run
```

```powershell
docker compose cp ..\gold-backtest\XAUUSD_H1.csv backend:/tmp/bt_h1.csv
```

```powershell
docker compose exec backend python -m gold_trading.ingestion.cli import-csv /tmp/bt_h1.csv --server-tz Europe/Athens --timeframe H1 --dry-run
```

(`..\gold-backtest` = thư mục `C:\gold-backtest` vừa tạo. `--dry-run` dừng trước khi mở cơ sở dữ liệu — chỉ đọc file trong `/tmp` của container. H4 / D1 chưa đọc thử được vì lệnh chưa hỗ trợ — làm ở bước 2.)

**5. Gửi cho người phát triển:** ngày đầu / cuối / số thanh của 4 khung (bước 2–3) + **toàn bộ** nội dung 2 lệnh `--dry-run` in ra. Mong đợi: "Đọc được … nến, 0 dòng lỗi", khoảng thời gian UTC từ 2023 tới hôm nay, **không** có chữ "TỪ CHỐI". Có "TỪ CHỐI … múi giờ" → gửi nguyên văn (kèm dòng "Gợi ý"), không tự sửa.

**Giữ nguyên 4 file trong `C:\gold-backtest`** — đó là dữ liệu sẽ nạp vào DB riêng của backtest ở bước 10.

## Nhật ký kế hoạch

- **2026-11-17** — Viết bản nháp kế hoạch (chưa code) theo DEC-29. Đọc code thật trên `develop` `0cdae0e`. Phát hiện khi đọc: (1) `import-csv --dry-run` chỉ đọc file, không mở DB → dùng được cho bước 0 trong đợt đếm 5 ngày; (2) Technical cần H1 / H4 / D1 (MTF) — thiếu sẽ đổi hành vi Fusion, mà CSV chưa nhận H4 / D1 → bước 0 xuất cả 4 khung, bước 2 thêm H4 / D1; (3) lịch kinh tế đã lưu có `available_at` 11/2026 → replay 2 năm trước sẽ "không thấy tin" (lạc quan sai) → Q1, chặn cả ngày khi không dựng lại được; (4) News không có lịch sử → × 0,9 → Q4; (5) Risk đọc spread theo phút (chỉ có từ 11/2026) → backtest dùng spread nến làm proxy, đo độ lệch trên đoạn trùng → Q6; (6) `StrategyRunner` / `PaperBroker` gắn cổng thật + thời gian thật → backtest gọi thẳng `decide` / `Manager` / công thức Risk qua cổng lịch sử. Chờ người dùng duyệt (Q0) rồi làm bước 0.
- **2026-11-17** — **Người dùng duyệt cả bản (Q0 = A).** Tiếp: người dùng làm bước 0 (xuất XAUUSD M15 + H1 / H4 / D1 ra `C:\gold-backtest`, đọc thử `--dry-run`) khi rảnh, ngoài khung tin; gửi kết quả → ghi vào nhật ký này → bước 1 ở phiên chat mới.

- **2026-11-23** — Người dùng hỏi code được chưa (đã đủ 5 ngày chạy liên tục — chưa phải Gate) → chọn **(A)**: code ngay phần không cần dữ liệu thật, bước 0 làm khi rảnh. **Bước 1 xong**: nhánh `gd6-backtest`, mốc test, thiết kế 39 (dùng lại nguyên `RiskEngine` qua cổng lịch sử + đồng hồ mô phỏng, `RiskLedger`, `PaperBroker.fill`, `PaperMonitor`; chỉ thêm `BarBroker` dò SL / TP theo nến; DB riêng từ chối khi trùng `DATABASE_URL`; bias 1–9). Trước đó: sửa test GĐ1 phụ thuộc ngày (CI `develop` đỏ từ 21/11) trên `develop`.

- **2026-11-23** — **Bước 6 phần hàm thống kê xong** (`backtest/stats.py`): Sharpe / độ lệch / độ nhọn, hệ số lợi nhuận, tỷ lệ lệnh lãi, chuỗi thua, sụt giảm theo tỷ lệ, bootstrap theo khối ngày, DSR, PBO (CSCV). Thiếu dữ liệu → `None`, không trả vô cực. Còn của bước 6: mốc ngẫu nhiên, mốc không lọc, chia nhóm — sau bước 5. Test backend 2853 passed, 3 skipped.

- **2026-11-23** — **Bước 7 phần thuần xong** (`backtest/protocol.py`, 8 test). Soát riêng 5.000 khoảng dữ liệu ngẫu nhiên **bắt được lỗi thật**: ngày bắt đầu 29–31 + cộng dồn 3 tháng bị trôi → đoạn kiểm hở / chồng (37 ca) → sửa: mọi mốc tính từ mốc gốc; thêm test (đột biến về mã cũ → đỏ); soát lại 0 lỗi. Còn của bước 7: bảng đăng ký + khóa đoạn để dành trong DB backtest (cần DB riêng — cùng bước 2 / 5).

- **2026-11-23** — **Bước 5 xong (phần mô phỏng)**: dùng lại nguyên luồng thật qua cổng lịch sử + đồng hồ mô phỏng; `StrategyRunner` nhận thêm chế độ `BACKTEST` (một dòng). Soát riêng: 3 bộ giá đi ngẫu nhiên 3 tháng (~6.000 nến, ~75 lệnh / bộ, có khoảng trống giá) → 0 lỗi bất biến (không chồng lệnh, chỉ vào trong giờ, không qua đêm, sổ tiền khớp, lỗ vượt rủi ro chỉ khi có khoảng trống giá); tốc độ ~1,5 giây / 3 tháng. Phát hiện: bảng ngày lễ chỉ phủ 2024–2027 → dữ liệu 2023 sẽ bị chặn hết (ghi bias 0, xử lý ở bước 2). Luật mới ghi trước: mở lại sau dừng ở mốc ngày kế tiếp (thiết kế 39 mục 5a).

- **2026-11-23** — **Bước 6 xong** (phần không cần dữ liệu thật): chỉ số + chia nhóm, mốc ngẫu nhiên, mốc không lọc, mua – giữ. Tăng tốc mô phỏng (bảng spread dựng một lần, equity chỉ tính khi đang dừng): 2,5 năm ~1,8 giây / lần khi ít lệnh. **Soát riêng — "thước đo"** (giá đi ngẫu nhiên 6 tháng, 100 lần mốc): nhận định cài sẵn lợi thế → kỳ vọng +0,85 / +0,91R **vượt** p95 mốc (+0,13 / +0,12R); nhận định bốc thăm → +0,07R **không vượt** (+0,14 / +0,09R) — 2 hạt giống. **Lỗi tìm được khi soát:** bốc đúng n thời điểm chỉ khớp ~55 % (va lệnh đang mở / nghỉ / 4 lệnh ngày) → không "cùng số lệnh" → thêm hiệu chỉnh số lần bốc (≤ 8 vòng) → khớp ~95 %. Thời gian: mốc 1.000 lần trên 2,5 năm ước ~4 giờ với 4 nhân — chạy một lần trên máy, có thể cần tăng tốc thêm (ghi thiết kế 39 mục 13).

- **2026-11-23** — **Bước 7 xong** (phần không cần dữ liệu thật): đăng ký chỉ-thêm (migration 0028), walk-forward theo lát cắt, chặn đọc đoạn để dành, chạy để dành một lần. **Phát hiện khi viết test:** sổ paper trong bộ nhớ của GĐ5 chậm theo bình phương khi nhiều lệnh (84 giây / 669 lệnh) → `FastLedger` có chỉ mục (18,5 giây), chứng minh tương đương bằng bộ test GĐ5 + so từng lệnh. Không đổi code GĐ5 (chỉ thêm lớp con trong `backtest/`; test GĐ5 chạy thêm loại sổ `fast`). Test backend 2961 passed, 3 skipped.

- **2026-11-23** — **Bước 8 xong** (trừ HTML + lệnh CLI — cần DB riêng, làm cùng bước 2 / 10): luật chấm T1–T8 ghi trước trong thiết kế 39 mục 12; chấm thuần + tính số từ walk-forward + báo cáo Markdown + cảnh báo 6-C04; 6-C05 có test. Soát đột biến: 11/12 bắt ngay, 1 lọt (T7 để dành đúng 0R khi ngoài mẫu âm) → thêm test.

## Prompt cho phiên mới

**Đã duyệt 17/11.** Sau khi người dùng làm xong bước 0 (kết quả ghi ở nhật ký), dán:

Làm tiếp GĐ6 (Backtest) theo docs/ke-hoach/GD6-ke-hoach.md — làm song song theo DEC-29. Đọc CLAUDE.md, PROGRESS.md, docs/giai-doan/GD6-backtest.md, docs/ke-hoach/GD6-ke-hoach.md (kết quả bước 0 ở nhật ký). Code trên nhánh `gd6-backtest` tách từ `develop`; không gộp vào `develop` tới sau Gate GĐ1 + GĐ2; máy người dùng không dựng lại tới sau Gate. Làm từ bước 1, hỏi Q1–Q7 khi tới bước cần (mỗi lần một câu, 2–3 lựa chọn + khuyến nghị). Không nạp gì vào DB đang chạy. Người dùng không rành kỹ thuật; PowerShell không `\"` / `$`; không bao giờ yêu cầu dán mật khẩu / token / khóa API. Trả lời tiếng Việt.
