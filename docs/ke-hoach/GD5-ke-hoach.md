# GĐ5 — Kế hoạch giao dịch (hồ sơ rủi ro + chiến lược + Risk Engine + Ledger paper): kế hoạch + checklist

> Tạo 2026-11-16. Nguồn sự thật cho mã việc / case: [`docs/giai-doan/GD5-ke-hoach-giao-dich.md`](../giai-doan/GD5-ke-hoach-giao-dich.md). Đặc tả: `docs/huong-dan-chuc-nang/06-strategy-engine.md`, `07-risk-engine-va-ledger.md`. Xong bước nào tick ở **cả hai** file.
>
> **Trạng thái: BẢN NHÁP — CHỜ NGƯỜI DÙNG DUYỆT. Chưa code.**
>
> **Làm song song (DEC-28, người dùng 2026-11-16).** **Không đóng GĐ5 trước GĐ1 → GĐ2 → GĐ3 → GĐ4.** Việc kiểm trên máy GĐ1/GĐ2 theo [`lich-kiem-tren-may.md`](lich-kiem-tren-may.md) được ưu tiên (phiên nào có việc kiểm trên máy thì làm việc đó trước). **Không có lệnh thật nào:** GĐ5 chỉ tạo ý định (`TradeIntent`) + quyết định Risk + sổ cái **paper**; không gọi Gateway để gửi lệnh (gửi lệnh từ GĐ8/GĐ9). **Không tự đặt số rủi ro** — mọi con số rủi ro / ngưỡng lỗ lấy từ tài liệu quản lý vốn của người dùng (KN-12, DEC-09: 0,25–0,5 %/lệnh + ngưỡng lỗ ngày/tuần là luật cứng); chưa có số → Risk **từ chối mọi intent** (mặc định an toàn).

## Nhánh code

- Code GĐ5 làm trên **nhánh riêng tách từ `claude/affectionate-einstein-8ypy59`** (đã gồm KN-03 spread theo phút — `market/quote_minutes.py`, đã gộp từ `claude/vigilant-hopper-f4wuqk`; KN-05 lịch sử thông số broker — `storage/broker_history.py`, `spec_at`, migration 0023; KN-21 `model_copy` kiểm lại). Tên đề xuất: `gd5-rui-ro` (đặt khi bắt đầu code).
- **Chưa lên `develop`** cho tới khi người dùng chọn lịch dựng lại (sau Gate GĐ1 + GĐ2, sau khi nhánh chờ đã lên). Migration GĐ5 đánh số **sau 0023**; nếu nhánh chờ đổi số trước khi lên `develop` → đánh lại số trước khi gộp.
- Mỗi bước: test + ruff (+ `npm run build` nếu sửa giao diện), **kiểm mã thoát thật** (`echo $?` / `PIPESTATUS`, không dựa vào chữ "passed"), rồi commit (nhắc mã việc) → push nhánh GĐ5 → kiểm CI (job `docker` TimescaleDB thật).

## Hiện trạng code (đọc ngày 16/11 trên nhánh chờ)

- `risk/engine.py`: `RiskEngine.evaluate(intent, view, ctx)` — **bên gọi đưa** `MarketView` và `SafetySupervisor`; hỏi `SafetySupervisor.allows_new_orders()` (chỉ xét ACTIVE, **không thấy lệnh cấm làn nhanh** DEC-20) → F-02 / KN-01. Khối lượng = rủi ro / (khoảng SL × `contract_size=100` hằng số); **không** cộng spread / trượt giá / phí; `max_spread=0,5` cố định; `max_risk_per_trade=0,005`, `max_total_reserved=0,02` là **số đặt sẵn trong code** (chưa phải số người dùng chốt) → KN-02. Tiền dùng `float`.
- `risk/ledger.py`: sổ reserve/release chỉ-thêm **trong bộ nhớ** (mất khi khởi động lại).
- `accounts/runtime.py:153` `AccountRegistry.allows_new_orders(tài khoản)`: Safety ACTIVE + chủ tài khoản không bị khóa + không còn lệnh cấm làn nhanh; đọc lỗi → `False`.
- `storage/market_views.py` `current(scope, at)`: MarketView mới nhất đã biết của đúng nguồn giá, còn hạn và chưa bị vô hiệu; không lùi bản cũ.
- `storage/broker_history.py` `spec_at(tài khoản, mã, lúc)`: thông số broker tại thời điểm (cỡ hợp đồng, point, digits, lot min/max/bước, stops/freeze level, swap, đòn bẩy, tiền lợi nhuận, tiền tài khoản). **Không có** giá trị tick (`trade_tick_value`) và **không có** phí hoa hồng (MT5 không báo phí trong thông số mã).
- `market/quote_minutes.py`: spread theo phút (trung vị, p95, lớn nhất — đơn vị point), giữ vĩnh viễn; đọc point-in-time.
- `strategy/`: trống. Risk Engine **chưa nằm trong luồng thật nào** (chỉ test).

## Ý tưởng chính

- **Risk là cổng cuối và tự đi hỏi**: lúc quyết, Risk tự đọc trạng thái thật (cổng tài khoản, MarketView hiện hành, thông số broker, equity, spread) — không tin dữ liệu do bên gọi đưa. Thiếu / cũ / lỗi đọc → `REJECTED` có lý do.
- **Rủi ro thật ≤ mức được duyệt**: rủi ro một lệnh = lỗ khi chạm SL **+ spread + trượt giá ước tính + phí** (+ swap nếu giữ qua đêm), theo thông số **thật** của broker tại lúc quyết. Lot làm tròn **xuống**; dưới lot tối thiểu → từ chối, nói rõ thiếu bao nhiêu (5-C01).
- **Không số nào tự bịa**: số rủi ro từ hồ sơ rủi ro người dùng duyệt (có phiên bản); số kỹ thuật chưa hiệu chỉnh (vd. hệ số trượt giá) ghi là "giá trị khởi đầu chưa hiệu chỉnh" + lý do trong thiết kế, sau đó vào sổ tham số (KN-08).
- **Tiền dùng `Decimal`** ở mọi phép tính tiền / rủi ro / PnL mới (CORE-05).
- **Ngoài phạm vi GĐ5:** gửi lệnh, Execution, Guardian EA (GĐ8/GĐ9); backtest (GĐ6); hiệu chỉnh xác suất (GĐ7). Cờ `UNVALIDATED_RULES` vẫn chặn SHADOW/LIVE (DEC-25) — GĐ5 chỉ chạy PAPER.

## Thứ tự làm (mỗi bước: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick → commit → push nhánh GĐ5 → kiểm CI)

### Bước 0 — Chuẩn bị (không đổi hành vi)
- [ ] Tạo nhánh GĐ5 từ `claude/affectionate-einstein-8ypy59`; chạy test gốc (backend, mt5_gateway, frontend) + ruff, ghi số làm mốc.
- [ ] Thiết kế `docs/thiet-ke/35-risk-engine.md` (khung): luồng quyết định, danh sách lý do từ chối, đơn vị (giá / point / tiền tài khoản), nguồn của từng số (thông số broker, hồ sơ rủi ro, giá trị khởi đầu chưa hiệu chỉnh). Viết **trước** khi code bước 1–2.

### Bước 1 — RSK-10 (KN-01, BẮT BUỘC, ĐẦU TIÊN): Risk tự đọc cổng thật lúc quyết; 5-C14, 5-C15
- [ ] `RiskEngine` nhận **các cổng đọc** thay vì giá trị: `AccountRegistry` (gọi `allows_new_orders(account_id)` — Safety + khóa người dùng + lệnh cấm làn nhanh DEC-20) và `MarketViewStore` (gọi `current(nguồn giá của tài khoản, now)`). **Bỏ** tham số `SafetySupervisor` và `MarketView` do bên gọi đưa; intent chỉ mang `market_view_id` → Risk so với MarketView hiện hành (khác id / không có → `REJECTED`).
- [ ] Đọc cổng ném lỗi → `REJECTED` (`GATE_READ_ERROR`), không ném lên người gọi, không cho qua.
- [ ] Sửa ghi chú RSK-01 trong file giai đoạn (trước đây "Kiểm Safety" chưa gồm DEC-20).
- [ ] **Ghi chú KN-14 (nguồn lịch hỏng mà không có bản ghi lịch mới → MarketView tạo lúc nguồn còn khỏe dùng được tới 15 phút):** **Q1 chốt 16/11: Risk tự kiểm** — Risk đọc sức khỏe nguồn lịch lúc quyết (lần nạp gần nhất lỗi hoặc quá hạn → `REJECTED` `CALENDAR_SOURCE_UNHEALTHY`), không chờ MarketView hết hạn. Ngưỡng "quá hạn" lấy theo chu kỳ nạp sẵn có của nguồn lịch (ghi thiết kế 35); test: nguồn lỗi + MarketView còn hạn → `REJECTED`.
- [ ] Test: lệnh cấm làn nhanh còn hạn + Safety ACTIVE → `REJECTED` (5-C14); MarketView bị vô hiệu sau khi tạo intent, trước lúc duyệt → `REJECTED` (5-C15); chủ tài khoản bị khóa → `REJECTED`; nguồn giá khác → không thấy MarketView; cổng đọc lỗi → `REJECTED`; test cũ của RSK-01 / 4-C05 / 4-C06 chuyển sang API mới vẫn đúng.
- [ ] Soát riêng: `create_app` thật (SQLite) + orchestrator + làn nhanh thật: tạo lệnh cấm qua đường thật (sự kiện HIGH / spread giãn) → Risk từ chối; vô hiệu MarketView qua Fusion thật → Risk từ chối. Đột biến: đổi Risk về hỏi `SafetySupervisor` → test 5-C14 phải đỏ.

### Bước 2 — RSK-11 (KN-02, BẮT BUỘC): khối lượng + rủi ro theo thông số thật; 5-C01, 5-C02, 5-C16 (+ RSK-08, CORE-05 phần Risk)
- [ ] **2a — Thông số broker tại lúc quyết:** đọc `spec_at(tài khoản, mã broker, now)` (KN-05). Không có dòng / thiếu trường cần (cỡ hợp đồng, point, lot min/max/bước, tiền lợi nhuận, tiền tài khoản) → `REJECTED` `BROKER_SPEC_MISSING`. Thông số quá cũ so với nhịp tim (Gateway mất kết nối) → `REJECTED`. **Bỏ** `SymbolSpec` hằng số (`contract_size=100`). Cách quy đổi tiền khi tiền lợi nhuận ≠ tiền tài khoản: theo **câu hỏi Q2**.
- [ ] **2b — Equity thật:** equity lấy từ nhịp tim Gateway mới nhất của tài khoản (không do bên gọi đưa); quá cũ / không có → `REJECTED` `EQUITY_STALE`. Tuổi tối đa: giá trị khởi đầu chưa hiệu chỉnh, ghi thiết kế 35.
- [ ] **2c — Chi phí vào rủi ro:** rủi ro / lot = (khoảng SL + spread hiện tại + trượt giá ước tính) × giá trị một đơn vị giá / lot **+ phí khứ hồi / lot**. Phí: theo **câu hỏi Q3**. Trượt giá ước tính: theo **câu hỏi Q4**. Khối lượng = rủi ro cho phép / rủi ro mỗi lot, làm tròn **xuống** theo bước lot; < lot tối thiểu → `REJECTED` `BELOW_MIN_VOLUME` + số tiền / vốn còn thiếu (5-C01); > lot tối đa → cắt về tối đa. Tính bằng `Decimal`.
- [ ] **2d — Ngưỡng spread theo phân bố của chính sàn** thay `max_spread=0,5`: theo **câu hỏi Q5** (dùng spread theo phút KN-03 của đúng nguồn giá, đọc point-in-time; không đủ dữ liệu → `REJECTED` `SPREAD_BASELINE_MISSING`, không đoán).
- [ ] **2e — RSK-08 (stops / freeze level, 5-C02):** SL gần hơn `max(stops_level × point, spread hiện tại)` → `REJECTED` `SL_TOO_CLOSE`; SL quá xa (rủi ro 1 lot tối thiểu đã vượt mức) → rơi vào 5-C01.
- [ ] Test **tính tay** (bảng trong thiết kế 35): tài khoản USD + 1 lot = 100 oz; broker 1 lot ≠ 100 oz (vd. 10 oz, 1 oz); tài khoản khác tiền (theo Q2); spread + trượt + phí làm lot nhỏ đi đúng số (5-C16); lot làm tròn xuống, không bao giờ lên; thiếu thông số / equity cũ / thiếu nền spread → từ chối; `stops_level` `NULL` (Gateway không đọc được) → coi như chưa biết → từ chối (không coi là 0).
- [ ] Soát riêng: viết lại công thức độc lập (bảng tra / phân số chính xác) so trên hàng nghìn tổ hợp ngẫu nhiên → lệch 0; bất biến "rủi ro thật (gồm chi phí) ≤ mức được duyệt" trên mọi tổ hợp; Postgres + TimescaleDB qua CI.

### Bước 3 — Hồ sơ rủi ro có phiên bản (DB-07, RPF-01; DEC-09 / KN-12) — CẤU TRÚC, CHƯA CÓ SỐ
- [ ] Bảng `risk_profiles` chỉ-thêm (migration sau 0023), mỗi tài khoản một chuỗi phiên bản; ai tạo, lúc nào, lý do; trigger chặn sửa / xóa. Trường theo 9 câu hỏi KN-12 (rủi ro / lệnh, ngưỡng lỗ ngày / tuần + mốc reset + múi giờ, chuỗi thua, drawdown dừng hẳn, số lệnh mở / tổng rủi ro mở, qua đêm / cuối tuần / qua tin, tăng rủi ro khi lãi, nạp / rút).
- [ ] Kiểm hợp lệ cứng: rủi ro / lệnh **trong [0,25 %; 0,5 %]** (DEC-09) — ngoài khoảng → không lưu được. Mục tiêu 4–5 %/ngày nếu có chỉ lưu làm ghi chú, **không** đi vào phép tính nào.
- [ ] `RiskPolicy` **bỏ số mặc định** (`0,005`, `0,02`): Risk đọc hồ sơ hiện hành của tài khoản; **chưa có hồ sơ → `REJECTED` `NO_RISK_PROFILE`**. Hồ sơ đổi giữa lúc tính và lúc duyệt → tính lại dưới khóa (5-C13).
- [ ] Ai được tạo hồ sơ: theo **câu hỏi Q6**.
- [ ] Số cụ thể: **chờ tài liệu "Quản lý vốn khi trade vàng"** (KN-12). Test dùng số giả có nhãn rõ "chỉ để test".

### Bước 4 — Hạn mức theo thời gian + danh mục (RSK-05, RSK-04, RSK-06; 5-C05, 5-C06, 5-C12, 5-C13)
- [ ] RSK-05: lỗ ngày / tuần (mốc reset + múi giờ theo hồ sơ, test đổi giờ DST), drawdown từ đỉnh, chuỗi thua — tính từ equity thật (lịch sử equity theo giờ KN-05 + nhịp tim) **và** PnL paper của sổ cái. Chạm ngưỡng → chặn lệnh mới tới kỳ sau + đề nghị Safety `PAUSED` (Safety có quyền cao nhất; Risk không tự mở lại). Số ngưỡng: từ hồ sơ (bước 3).
- [ ] RSK-04: exposure ròng / gộp theo mã, số lệnh mở tối đa, tổng rủi ro mở (gồm reservation đang mở) — theo hồ sơ.
- [ ] RSK-06: `REDUCED` có lý do cụ thể (hạn mức nào cắt), TTL quyết định, gắn phiên bản chính sách **và** phiên bản hồ sơ rủi ro.
- [ ] Test: chạm ngưỡng ngày → chặn tới mốc reset kế tiếp (gồm ngày đổi DST); chuỗi thua; hai intent đồng thời (8 luồng) không vượt tổng; equity đổi giữa chừng.

### Bước 5 — Margin + chi phí qua đêm (RSK-03, RSK-09; 5-C07, 5-C08, 5-C09)
- [ ] RSK-03: margin cần ≈ khối lượng × cỡ hợp đồng × giá / đòn bẩy (đòn bẩy + margin trống từ thông số / nhịp tim thật); không đủ → giảm khối lượng hoặc `REJECTED` (5-C09); đòn bẩy bị broker đổi → dùng giá trị tại lúc quyết (KN-05).
- [ ] RSK-09: swap theo `swap_mode` thật (chỉ hỗ trợ các kiểu đã kiểm; kiểu lạ → không cho giữ qua đêm), thứ Tư (hoặc ngày `swap_rollover3days`) ×3; cộng vào rủi ro khi chính sách cho giữ qua đêm.
- [ ] 5-C07 qua cuối tuần: theo hồ sơ (cấm, hoặc cho kèm rủi ro gap — cách tính gap là giá trị khởi đầu chưa hiệu chỉnh, chỉ đặt khi người dùng chọn "cho").
- [ ] Test tính tay margin / swap với số broker giả có nhãn; `swap_mode` lạ → chặn qua đêm.

### Bước 6 — Sổ cái paper bền vững (DB-06, LED-02, LED-04, LED-05; CORE-05)
- [ ] Migration bảng reservation / ý định / quyết định / lệnh paper / vị thế paper (chỉ-thêm, sự kiện bù trừ có lý do + người làm + liên kết bản gốc). `RiskLedger` bản SQL + bản bộ nhớ, cùng giao diện; khóa ở DB (giao dịch + khóa hàng) để hai tiến trình không cùng vượt hạn mức.
- [ ] LED-04: "khớp" paper giả lập (giá ask/bid thật của nguồn giá lúc đó + trượt giá ước tính) → exposure + PnL `Decimal`; đóng lệnh khi chạm SL/TP theo giá thật (chỉ nến / giây đã có — không nhìn trước).
- [ ] LED-05: khởi động lại giữa reserve và "gửi" → khôi phục từ DB qua `idempotency_key`; reservation hết hạn mà không có lệnh → nhả (sự kiện bù trừ).
- [ ] Test: crash giả lập ở từng điểm; trùng `idempotency_key` → một luồng; 8 luồng tranh ngân sách trên Postgres; Postgres + TimescaleDB qua CI.

### Bước 7 — Chiến lược v1 (STR-06 trước, rồi STR-02..05; 5-C03, 5-C04, 5-C11)
- [ ] **STR-06 — Văn bản chiến lược v1** ở `docs/thiet-ke/36-chien-luoc-v1.md`, **người dùng duyệt trước khi code**: điều kiện vào (MarketView còn hạn, nghiêng LONG/SHORT, confidence đạt ngưỡng theo regime, không cờ cấm), phiên giao dịch, cửa sổ cấm (tin), SL theo ATR, TP theo R:R, BE, trailing, time-stop, số lệnh tối đa, tín hiệu ngược chiều khi đang có lệnh (5-C03). Mọi ngưỡng là giá trị khởi đầu chưa hiệu chỉnh (GĐ6 đo). Cách viết: theo **câu hỏi Q7**.
- [ ] STR-02/03: `strategy/` sinh `TradeIntent` (entry, SL, TP, `risk_budget_requested` = mức của hồ sơ, `expiry` ngắn, `idempotency_key` xác định từ chiến lược + mã + khung + MarketView) — **không tự suy khối lượng**.
- [ ] STR-04 / 5-C04: chống trùng cho cùng chiến lược / mã / khung; giới hạn số intent.
- [ ] STR-05: audit (lưu intent + quyết định Risk + lý do từ chối), chạy mỗi khi có MarketView mới (sau Fusion trong nhịp orchestrator) → Risk → sổ cái paper. **Không** có đường nào tới Gateway gửi lệnh (test khẳng định).
- [ ] Soát riêng: chạy trên nến mẫu nhiều ngày qua orchestrator thật → không intent nào khi MarketView hết hạn / bị vô hiệu / NEUTRAL; SAMPLE luôn có nhãn; Risk từ chối hết khi chưa có hồ sơ rủi ro.

### Bước 8 — Kế hoạch khả thi + trang Rủi ro (RPF-02..05, DSH-05)
- [ ] RPF-02/03: báo cáo khả thi bằng số cụ thể: với vốn + thông số broker thật + ATR M15 **đo thật** + spread thật → SL đề xuất, lot, rủi ro thật gồm chi phí, vốn tối thiểu để lot nhỏ nhất nằm trong 0,25 % / 0,5 % (ví dụ tính tay trong đánh giá: SL ≈ 19,5 USD ở 0,01 lot → ≈ 3.900 / 7.800 USD — **phải tính lại bằng số thật**). Lệnh `cli kha-thi` (chỉ đọc) để chạy trên máy người dùng.
- [ ] RPF-04: SAMPLE → nhãn "chỉ minh họa", không bao giờ dẫn tới quyết định thật.
- [ ] RPF-05 / DSH-05: trang **Rủi ro** — hồ sơ hiện hành + lịch sử phiên bản, hạn mức đã dùng hôm nay / tuần này, reservation đang mở, quyết định Risk gần đây + lý do (tiếng Việt), báo cáo khả thi. OpenAPI + `npm run gen:api`; test API + giao diện.

### Bước 9 — Tài liệu cuối GĐ5 (KN-08, KN-07 — cân nhắc, người dùng duyệt)
- [ ] KN-08 — **Sổ tham số** `docs/thiet-ke/so-tham-so.md`: mọi ngưỡng chưa hiệu chỉnh (GĐ2–GĐ5) với giá trị, phiên bản, lý do, có được tối ưu ở GĐ6 không.
- [ ] KN-07 — **Giao thức đánh giá đăng ký trước** (bản nháp cho GĐ6): walk-forward, đoạn ngoài mẫu không đụng tới, số lệnh tối thiểu, chỉ số sau chi phí, so mốc ngẫu nhiên, Deflated Sharpe / PBO. Viết **trước** khi chạy backtest; tiêu chí (BT-04) người dùng duyệt.

### Bước 10 — Gate GĐ5
- [ ] Mọi case 5-C01..C16 có test (ghi tên test vào bảng case)
- [ ] Người dùng duyệt hồ sơ rủi ro (DEC-09 / KN-12) và văn bản chiến lược (STR-06)
- [ ] Báo cáo khả thi trên dữ liệu thật của máy người dùng (`cli kha-thi`)
- [ ] **Gate GĐ1 → GĐ2 → GĐ3 → GĐ4 đã đóng** (DEC-28)
- [ ] Người dùng xác nhận

## Câu hỏi cần người dùng trả lời (hỏi lần lượt, mỗi lần một câu)

| Mã | Câu hỏi | Cần cho | Trả lời |
| --- | --- | --- | --- |
| Q1 | Nguồn lịch hỏng mà chưa có bản ghi mới → nhận định cũ còn dùng được tới 15 phút (ghi chú KN-14). Risk có tự kiểm sức khỏe nguồn lịch lúc quyết không? | Bước 1 | **Chốt 16/11: Risk tự kiểm.** Lúc duyệt, Risk tự xem sức khỏe nguồn lịch (lần nạp gần nhất lỗi / quá hạn) → lỗi thì `REJECTED` ngay, không chờ nhận định hết hạn 15 phút. Chấp nhận có thể từ chối nhầm vài lần khi trang lịch chập chờn |
| Q2 | Tiền lợi nhuận của mã vàng khác tiền tài khoản (vd. tài khoản cent, tài khoản EUR): quy đổi thế nào? | Bước 2a | chờ |
| Q3 | Phí hoa hồng / lot (MT5 không báo trong thông số mã): lấy từ đâu? | Bước 2c | chờ |
| Q4 | Trượt giá ước tính khi chưa có lệnh thật để đo | Bước 2c | chờ |
| Q5 | Ngưỡng "spread quá rộng" của Risk theo phân bố spread của chính sàn | Bước 2d | chờ |
| Q6 | Ai được tạo / đổi hồ sơ rủi ro (USER chủ tài khoản, ADMIN, hay USER tạo + ADMIN duyệt) | Bước 3 | chờ |
| Q7 | Văn bản chiến lược v1: người phát triển soạn nháp từ luật GĐ4 để người dùng duyệt, hay người dùng có chiến lược riêng gửi vào | Bước 7 | chờ |
| KN-12 | 9 câu về quản lý vốn (đánh giá độc lập mục 5.D) — **lấy từ tài liệu người dùng gửi**, không hỏi đoán | Bước 3–5 | chờ tài liệu |

Bước 0–2 chỉ cần Q1–Q5; bước 3 trở đi làm được phần cấu trúc trước khi có số (KN-12), Risk từ chối mọi intent tới khi có hồ sơ.

## Kiểm trên máy người dùng (điền chi tiết khi tới)

- Chỉ sau khi người dùng chọn lịch dựng lại (sau Gate GĐ1 + GĐ2 và sau khi nhánh chờ lên `develop`). Không dựng lại trong đợt đếm 5 ngày, không trong khung công bố tin.
- Dự kiến: `cli kha-thi` (chỉ đọc) trên dữ liệu thật; trang Rủi ro hiện "Chưa có hồ sơ rủi ro — mọi lệnh bị từ chối" khi chưa nhập; sau khi nhập hồ sơ: quyết định Risk paper có lý do tiếng Việt, **không có lệnh nào xuất hiện trong MT5**.

## Nhật ký kế hoạch

- **2026-11-16** — Viết bản nháp kế hoạch (chưa code). RSK-10, RSK-11 đặt đầu tiên (bước 1–2) theo DEC-28; ghi chú KN-14 (15 phút) đưa vào bước 1 (Q1); số rủi ro chờ KN-12; KN-07, KN-08 cuối GĐ5 (bước 9). Phát hiện khi đọc code: thông số broker KN-05 **không có giá trị tick và phí hoa hồng** → Q2, Q3; `RiskPolicy` đang có số rủi ro đặt sẵn trong code (0,5 % / 2 %) → bước 3 bỏ số mặc định.

## Prompt cho phiên mới
Đọc CLAUDE.md, PROGRESS.md, rồi docs/ke-hoach/GD5-ke-hoach.md và chỉ các mục liên quan của docs/giai-doan/GD5-ke-hoach-giao-dich.md. GĐ5 làm song song (DEC-28): không đóng trước GĐ1 → GĐ4; kiểm trên máy GĐ1/GĐ2 (docs/ke-hoach/lich-kiem-tren-may.md) ưu tiên; không có lệnh thật nào; không tự đặt số rủi ro (chờ KN-12). Code trên nhánh GĐ5 tách từ claude/affectionate-einstein-8ypy59, chưa lên develop. Làm theo thứ tự bước, RSK-10 → RSK-11 trước. Quy trình: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick ở cả hai file, ghi nhật ký → chạy test + ruff, kiểm mã thoát thật → commit (nhắc mã việc) → push nhánh GĐ5 → kiểm CI. Người dùng không rành kỹ thuật: tiếng Việt đơn giản, mỗi lần hỏi một câu kèm 2–3 lựa chọn + khuyến nghị. Không bao giờ yêu cầu dán mật khẩu / token / khóa API vào chat.
