# GĐ5 — Kế hoạch giao dịch (hồ sơ rủi ro + chiến lược + Risk Engine + Ledger paper): kế hoạch + checklist

> Tạo 2026-11-16. Nguồn sự thật cho mã việc / case: [`docs/giai-doan/GD5-ke-hoach-giao-dich.md`](../giai-doan/GD5-ke-hoach-giao-dich.md). Đặc tả: `docs/huong-dan-chuc-nang/06-strategy-engine.md`, `07-risk-engine-va-ledger.md`. Xong bước nào tick ở **cả hai** file.
>
> **Trạng thái: NGƯỜI DÙNG ĐÃ DUYỆT 2026-11-16** (Q1–Q7 chốt). Code bước 0–2 ở **phiên chat mới** (người dùng chọn). Bước 3 trở đi: hỏi H1–H11 khi tới.
>
> **Làm song song (DEC-28, người dùng 2026-11-16).** **Không đóng GĐ5 trước GĐ1 → GĐ2 → GĐ3 → GĐ4.** Việc kiểm trên máy GĐ1/GĐ2 theo [`lich-kiem-tren-may.md`](lich-kiem-tren-may.md) được ưu tiên (phiên nào có việc kiểm trên máy thì làm việc đó trước). **Không có lệnh thật nào:** GĐ5 chỉ tạo ý định (`TradeIntent`) + quyết định Risk + sổ cái **paper**; không gọi Gateway để gửi lệnh (gửi lệnh từ GĐ8/GĐ9). **Không tự đặt số rủi ro** — mọi con số rủi ro / ngưỡng lỗ lấy từ tài liệu quản lý vốn của người dùng (KN-12, DEC-09: 0,25–0,5 %/lệnh + ngưỡng lỗ ngày/tuần là luật cứng); chưa có số → Risk **từ chối mọi intent** (mặc định an toàn). **16/11: người dùng đã gửi tài liệu "Quản lý vốn khi giao dịch vàng (XAU/USD)" v1.0** (16 chương + 7 phụ lục) — áp dụng ở mục "Áp dụng tài liệu Quản lý vốn" bên dưới. Tài liệu tự ghi mọi con số là **ví dụ minh họa** → số của hồ sơ rủi ro vẫn do người dùng chọn (hỏi từng câu), không chép số ví dụ.

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
- [x] Tạo nhánh GĐ5 từ `claude/affectionate-einstein-8ypy59`; chạy test gốc (backend, mt5_gateway, frontend) + ruff, ghi số làm mốc. *(16/11: nhánh `claude/fervent-hypatia-n3uyfn` = nhánh chờ + gộp nhánh kế hoạch. Mốc: backend 2330 passed, 2 skipped; mt5_gateway 206; frontend 140 test, check + build đạt; ruff sạch.)*
- [x] Thiết kế `docs/thiet-ke/35-risk-engine.md` (khung): luồng quyết định, danh sách lý do từ chối, đơn vị (giá / point / tiền tài khoản), nguồn của từng số (thông số broker, hồ sơ rủi ro, giá trị khởi đầu chưa hiệu chỉnh). Viết **trước** khi code bước 1–2.

### Bước 1 — RSK-10 (KN-01, BẮT BUỘC, ĐẦU TIÊN): Risk tự đọc cổng thật lúc quyết; 5-C14, 5-C15
- [x] `RiskEngine` nhận **các cổng đọc** thay vì giá trị: `AccountRegistry` (gọi `allows_new_orders(account_id)` — Safety + khóa người dùng + lệnh cấm làn nhanh DEC-20) và `MarketViewStore` (gọi `current(nguồn giá của tài khoản, now)`). **Bỏ** tham số `SafetySupervisor` và `MarketView` do bên gọi đưa; intent chỉ mang `market_view_id` → Risk so với MarketView hiện hành (khác id / không có → `REJECTED`).
- [x] Đọc cổng ném lỗi → `REJECTED` (`GATE_READ_ERROR`), không ném lên người gọi, không cho qua.
- [x] Sửa ghi chú RSK-01 trong file giai đoạn (trước đây "Kiểm Safety" chưa gồm DEC-20).
- [x] **Ghi chú KN-14 (nguồn lịch hỏng mà không có bản ghi lịch mới → MarketView tạo lúc nguồn còn khỏe dùng được tới 15 phút):** **Q1 chốt 16/11: Risk tự kiểm** — Risk đọc sức khỏe nguồn lịch lúc quyết (lần nạp gần nhất lỗi hoặc quá hạn → `REJECTED` `CALENDAR_SOURCE_UNHEALTHY`), không chờ MarketView hết hạn. Ngưỡng "quá hạn" lấy theo chu kỳ nạp sẵn có của nguồn lịch (ghi thiết kế 35); test: nguồn lỗi + MarketView còn hạn → `REJECTED`.
- [x] Test: lệnh cấm làn nhanh còn hạn + Safety ACTIVE → `REJECTED` (5-C14); MarketView bị vô hiệu sau khi tạo intent, trước lúc duyệt → `REJECTED` (5-C15); chủ tài khoản bị khóa → `REJECTED`; nguồn giá khác → không thấy MarketView; cổng đọc lỗi → `REJECTED`; test cũ của RSK-01 / 4-C05 / 4-C06 chuyển sang API mới vẫn đúng.
- [x] Soát riêng: `create_app` thật (SQLite) + orchestrator + làn nhanh thật: tạo lệnh cấm qua đường thật (sự kiện HIGH / spread giãn) → Risk từ chối; vô hiệu MarketView qua Fusion thật → Risk từ chối. Đột biến: đổi Risk về hỏi `SafetySupervisor` → test 5-C14 phải đỏ.

### Bước 2 — RSK-11 (KN-02, BẮT BUỘC): khối lượng + rủi ro theo thông số thật; 5-C01, 5-C02, 5-C16 (+ RSK-08, CORE-05 phần Risk)
- [x] **2a — Thông số broker tại lúc quyết:** đọc `spec_at(tài khoản, mã broker, now)` (KN-05). Không có dòng / thiếu trường cần (cỡ hợp đồng, point, lot min/max/bước, tiền lợi nhuận, tiền tài khoản) → `REJECTED` `BROKER_SPEC_MISSING`. Thông số quá cũ so với nhịp tim (Gateway mất kết nối) → `REJECTED`. **Bỏ** `SymbolSpec` hằng số (`contract_size=100`). **Q2 chốt 16/11:** chỉ tài khoản USD + tiền lợi nhuận USD (giá trị 1 USD giá / lot = cỡ hợp đồng thật); khác (USC, EUR…) hoặc trường tiền `NULL` → `REJECTED` `CURRENCY_UNSUPPORTED`. Giá trị tick từ Gateway làm khi người dùng chọn sàn thật (ghi việc mới vào file giai đoạn lúc đó).
- [x] **2b — Equity thật:** equity lấy từ nhịp tim Gateway mới nhất của tài khoản (không do bên gọi đưa); quá cũ / không có → `REJECTED` `EQUITY_STALE`. Tuổi tối đa: giá trị khởi đầu chưa hiệu chỉnh, ghi thiết kế 35.
- [x] **2c — Chi phí vào rủi ro** (đúng công thức tài liệu QLV mục 5.2 + 3.5: *khoảng SL thực = |vào − SL| + spread + buffer trượt giá*; *lot = tiền rủi ro / (khoảng SL thực × cỡ hợp đồng)*, làm tròn xuống; phí hoa hồng / oz cộng thêm; test lại đúng hai ví dụ tính tay của mục 5.2 — 0,20 lot và 0,17 lot / 98,6 USD — và tình huống 11.2 — 0,02 lot / 37,6 USD): rủi ro / lot = (khoảng SL + spread hiện tại + trượt giá ước tính) × giá trị một đơn vị giá / lot **+ phí khứ hồi / lot**. Phí (**Q3 chốt 16/11**): người dùng nhập "phí / lot" cho từng tài khoản (có phiên bản + audit); chưa nhập → `REJECTED` `COMMISSION_UNKNOWN`; 0 chỉ khi người dùng nhập 0. Trượt giá ước tính (**Q4 chốt 16/11: theo spread xấu của chính sàn**): đệm = p95 của `spread_p95` theo phút (KN-03) của đúng nguồn giá trong 30 ngày trước lúc quyết, đọc point-in-time, chỉ phút thị trường mở (bỏ phút có cờ `CALENDAR_CLOSED`); ít hơn số phút tối thiểu (ghi thiết kế 35) → `REJECTED` `SLIPPAGE_BASELINE_MISSING`, không đoán. Ghi rõ "giá trị khởi đầu chưa hiệu chỉnh — proxy, không phải trượt giá đo được"; đo lại bằng deal thật ở GĐ9 (vào sổ tham số KN-08). Không che được trượt giá lúc ra tin → xử lý bằng chặn vào lệnh quanh tin (DEC-20) + H7. Khối lượng = rủi ro cho phép / rủi ro mỗi lot, làm tròn **xuống** theo bước lot; < lot tối thiểu → `REJECTED` `BELOW_MIN_VOLUME` + số tiền / vốn còn thiếu (5-C01); > lot tối đa → cắt về tối đa. Tính bằng `Decimal`.
- [x] **2d — Ngưỡng spread theo phân bố của chính sàn** thay `max_spread=0,5` (**Q5 chốt 16/11**): spread hiện tại > **cùng mốc p95 30 ngày của câu Q4** → `REJECTED` `SPREAD_TOO_WIDE` (ghi cả spread hiện tại và ngưỡng); băng chặn làn nhanh (> 3 × trung vị 60 phút, DEC-20) giữ nguyên, hai lớp độc lập; ngưỡng là "giá trị khởi đầu chưa hiệu chỉnh" (sổ tham số KN-08) (dùng spread theo phút KN-03 của đúng nguồn giá, đọc point-in-time; không đủ dữ liệu → `REJECTED` `SPREAD_BASELINE_MISSING`, không đoán).
- [x] **2e — RSK-08 (stops / freeze level, 5-C02):** SL gần hơn `max(stops_level × point, spread hiện tại)` → `REJECTED` `SL_TOO_CLOSE`; SL quá xa (rủi ro 1 lot tối thiểu đã vượt mức) → rơi vào 5-C01.
- [x] Test **tính tay** (bảng trong thiết kế 35): tài khoản USD + 1 lot = 100 oz; broker 1 lot ≠ 100 oz (vd. 10 oz, 1 oz); tài khoản khác tiền (theo Q2); spread + trượt + phí làm lot nhỏ đi đúng số (5-C16); lot làm tròn xuống, không bao giờ lên; thiếu thông số / equity cũ / thiếu nền spread → từ chối; `stops_level` `NULL` (Gateway không đọc được) → coi như chưa biết → từ chối (không coi là 0).
- [x] Soát riêng: viết lại công thức độc lập (bảng tra / phân số chính xác) so trên hàng nghìn tổ hợp ngẫu nhiên → lệch 0; bất biến "rủi ro thật (gồm chi phí) ≤ mức được duyệt" trên mọi tổ hợp; Postgres + TimescaleDB qua CI.

### Bước 3 — Hồ sơ rủi ro có phiên bản (DB-07, RPF-01; DEC-09 / KN-12) — CẤU TRÚC, CHƯA CÓ SỐ
- [ ] Bảng `risk_profiles` chỉ-thêm (migration sau 0023), mỗi tài khoản một chuỗi phiên bản; ai tạo, lúc nào, lý do; trigger chặn sửa / xóa. Trường theo **mẫu kế hoạch cá nhân của tài liệu QLV (mục 10.1, 18 mục)** gộp với 9 câu hỏi KN-12 — xem bảng "Áp dụng tài liệu Quản lý vốn" (rủi ro / lệnh, ngưỡng lỗ ngày / tuần + mốc reset + múi giờ, chuỗi thua, drawdown dừng hẳn, số lệnh mở / tổng rủi ro mở, qua đêm / cuối tuần / qua tin, tăng rủi ro khi lãi, nạp / rút).
- [ ] Kiểm hợp lệ cứng: rủi ro / lệnh **trong [0,25 %; 0,5 %]** (DEC-09) — ngoài khoảng → không lưu được. Mục tiêu 4–5 %/ngày nếu có chỉ lưu làm ghi chú, **không** đi vào phép tính nào.
- [ ] `RiskPolicy` **bỏ số mặc định** (`0,005`, `0,02`): Risk đọc hồ sơ hiện hành của tài khoản; **chưa có hồ sơ → `REJECTED` `NO_RISK_PROFILE`**. Hồ sơ đổi giữa lúc tính và lúc duyệt → tính lại dưới khóa (5-C13).
- [ ] Ai được tạo hồ sơ (**Q6 chốt 16/11: (B) USER chủ tài khoản tự quyết**): chỉ chủ tài khoản tạo / sửa hồ sơ của tài khoản mình, có hiệu lực ngay (kể cả nới); **ADMIN không tạo / sửa / duyệt** hồ sơ của USER (đúng DEC-16: ADMIN không giao dịch). Vẫn giữ: giới hạn cứng DEC-09 (0,25–0,5 %/lệnh) do hệ thống chặn, không ai vượt được; mọi lần đổi lưu phiên bản + ai / lúc nào / lý do; intent đang chờ duyệt dùng phiên bản hồ sơ lúc quyết (tính lại dưới khóa, 5-C13).
- [ ] Số cụ thể: **chờ tài liệu "Quản lý vốn khi trade vàng"** (KN-12). Test dùng số giả có nhãn rõ "chỉ để test".

### Bước 4 — Hạn mức theo thời gian + danh mục (RSK-05, RSK-04, RSK-06; 5-C05, 5-C06, 5-C12, 5-C13)
- [ ] RSK-05: lỗ ngày / tuần (mốc reset + múi giờ theo hồ sơ, test đổi giờ DST), drawdown từ đỉnh, chuỗi thua — tính từ equity thật (lịch sử equity theo giờ KN-05 + nhịp tim) **và** PnL paper của sổ cái. Chạm ngưỡng → chặn lệnh mới tới kỳ sau + đề nghị Safety `PAUSED` (Safety có quyền cao nhất; Risk không tự mở lại). Số ngưỡng: từ hồ sơ (bước 3).
- [ ] Thêm theo tài liệu QLV: giới hạn lỗ **tháng** (mục 7.2), **số lệnh tối đa / ngày** (7.2), **bậc thang giảm rủi ro theo drawdown** (7.3 — bậc cao nhất không vượt mức rủi ro / lệnh trong hồ sơ, tức ≤ 0,5 % theo DEC-09; quay lại bậc cũ theo luật viết sẵn), **không tăng rủi ro sau chuỗi thắng** (7.4, mục 8 KN-12). Thay đổi hồ sơ: người dùng tự quyết, có hiệu lực ngay (Q6 = B; tài liệu QLV 10.3 khuyên tăng rủi ro chậm lại — người dùng đã cân nhắc và chọn tự quyết). Khối lượng **tự tăng / giảm theo equity** (tỷ lệ cố định, tài liệu 7.4) — người dùng đã xác nhận hợp lý 16/11.
- [ ] RSK-04: exposure ròng / gộp theo mã, số lệnh mở tối đa, **trần tổng rủi ro mở ("heat", 7.1)** gồm reservation đang mở; **mọi lệnh vàng cùng chiều tính là một vị thế** (7.5, tình huống 11.5). **Chặn bình quân giá lỗ / martingale** (chương 8): không thêm lệnh cùng chiều khi lệnh đang mở còn lỗ — chi tiết theo câu hỏi. **Kiểm tra gap** (7.6): tổng lot mở × cỡ hợp đồng × khoảng gap kịch bản ≤ mức chịu được trong hồ sơ.
- [ ] RSK-06: `REDUCED` có lý do cụ thể (hạn mức nào cắt), TTL quyết định, gắn phiên bản chính sách **và** phiên bản hồ sơ rủi ro.
- [ ] Test: chạm ngưỡng ngày → chặn tới mốc reset kế tiếp (gồm ngày đổi DST); chuỗi thua; hai intent đồng thời (8 luồng) không vượt tổng; equity đổi giữa chừng.

### Bước 5 — Margin + chi phí qua đêm (RSK-03, RSK-09; 5-C07, 5-C08, 5-C09)
- [ ] **Trần đòn bẩy thực tế** (tài liệu QLV 4.2: giá trị danh nghĩa mọi vị thế / equity ≤ trần trong hồ sơ — số do người dùng chọn), độc lập với đòn bẩy sàn cho.
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
- [ ] **STR-06 — Văn bản chiến lược v1** ở `docs/thiet-ke/36-chien-luoc-v1.md`, **người dùng duyệt trước khi code**: điều kiện vào (MarketView còn hạn, nghiêng LONG/SHORT, confidence đạt ngưỡng theo regime, không cờ cấm), phiên giao dịch, cửa sổ cấm (tin), SL theo ATR, TP theo R:R, BE, trailing, time-stop, số lệnh tối đa, tín hiệu ngược chiều khi đang có lệnh (5-C03). Mọi ngưỡng là giá trị khởi đầu chưa hiệu chỉnh (GĐ6 đo). Cách viết (**Q7 chốt 16/11: (A)**): người phát triển soạn nháp tiếng Việt đơn giản từ luật GĐ4 (MarketView + Technical / ATR), kèm ví dụ số; người dùng đọc, sửa, duyệt. **Chiến lược có phiên bản** (mỗi intent / quyết định gắn phiên bản chiến lược; bản cũ giữ lại, quay lại được); phiên bản mới — kể cả đổi một con số — là **chưa kiểm chứng** (DEC-25) cho tới khi backtest GĐ6 + người dùng duyệt; bản đã duyệt chạy thật không tự chuyển sang bản mới; đếm số lần sửa / số tham số (KN-07, KN-08) để tránh khớp quá mức.
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
| Q2 | Tiền lợi nhuận của mã vàng khác tiền tài khoản (vd. tài khoản cent, tài khoản EUR): quy đổi thế nào? | Bước 2a | **Chốt 16/11: USD trước, giá trị tick sau.** GĐ5 chỉ tính khi tài khoản USD **và** tiền lợi nhuận của mã = USD; khác → `REJECTED` `CURRENCY_UNSUPPORTED`. Khi người dùng chọn sàn thật: thêm `trade_tick_value` / `trade_tick_size` từ Gateway (cập nhật Gateway trên máy) để hỗ trợ tài khoản cent / tiền khác |
| Q3 | Phí hoa hồng / lot (MT5 không báo trong thông số mã): lấy từ đâu? | Bước 2c | **Chốt 16/11: nhập tay.** Mỗi tài khoản có trường "phí hoa hồng / lot (khứ hồi, tiền tài khoản)" do người dùng nhập theo trang của sàn, lưu có phiên bản + audit; **chưa nhập → `REJECTED` `COMMISSION_UNKNOWN`**; sàn không thu phí → người dùng phải chủ động nhập 0 (không tự hiểu là 0). Tài liệu QLV 3.5 xác nhận phải cộng phí vào rủi ro. Sau GĐ9: đối chiếu với phí thật trên deal MT5 |
| Q4 | Trượt giá ước tính khi chưa có lệnh thật để đo | Bước 2c | **Chốt 16/11: (A) theo spread xấu (p95, 30 ngày) của chính sàn**, ghi "chưa hiệu chỉnh", đo lại khi có lệnh thật |
| Q5 | Ngưỡng "spread quá rộng" của Risk theo phân bố spread của chính sàn | Bước 2d | **Chốt 16/11: (A)** từ chối khi spread lúc quyết vượt mức xấu p95 30 ngày của chính sàn (cùng mốc Q4); làn nhanh DEC-20 giữ nguyên |
| Q6 | Ai được tạo / đổi hồ sơ rủi ro (USER chủ tài khoản, ADMIN, hay USER tạo + ADMIN duyệt) | Bước 3 | **Chốt 16/11: (B) USER tự quyết**, có hiệu lực ngay; ADMIN không can dự. Giới hạn cứng DEC-09 vẫn do hệ thống chặn; mọi lần đổi có lịch sử |
| Q7 | Văn bản chiến lược v1: người phát triển soạn nháp từ luật GĐ4 để người dùng duyệt, hay người dùng có chiến lược riêng gửi vào | Bước 7 | **Chốt 16/11: (A)** người phát triển soạn nháp từ luật GĐ4, người dùng sửa + duyệt; chiến lược có phiên bản, sửa được về sau (bản mới = chưa kiểm chứng tới khi backtest + duyệt) |
| KN-12 | 9 câu về quản lý vốn (đánh giá độc lập mục 5.D) — **lấy từ tài liệu người dùng gửi**, không hỏi đoán | Bước 3–5 | chờ tài liệu |

## Áp dụng tài liệu Quản lý vốn (người dùng gửi 2026-11-16)

Tài liệu "Quản lý vốn khi giao dịch vàng (XAU/USD)" v1.0 là tài liệu giáo dục; **mọi con số trong đó là ví dụ** (tài liệu tự ghi). Hệ thống dùng **khung + công thức** của tài liệu; **con số** do người dùng chọn — hỏi lần lượt (H1, H2…) khi tới bước 3, mỗi câu kèm vùng tài liệu nêu + khuyến nghị thận trọng, luôn nằm trong DEC-09. Chưa chọn → Risk từ chối (`NO_RISK_PROFILE`).

| Mục mẫu 10.1 | Hệ thống dùng thế nào | Bước | Số |
| --- | --- | --- | --- |
| 1. Vốn rủi ro | Ghi chú hồ sơ; vốn thật đọc từ equity MT5. Báo cáo khả thi (RPF-03) so vốn với lot nhỏ nhất | 3, 8 | người dùng |
| 2. Mục tiêu giai đoạn | Chỉ ghi chú; **không** vào phép tính (DEC-09: 4–5 %/ngày chỉ tham khảo) | 3 | — |
| 3. Công cụ + khung + phiên | XAUUSD; khung / phiên thuộc văn bản chiến lược | 7 | STR-06 |
| 4. Rủi ro / lệnh | Luật cứng, chỉ nhận **0,25–0,5 %** (DEC-09; tài liệu bảng 5.1: "mới bắt đầu, chưa có thống kê" = 0,25–0,5 %) | 2–3 | **H1 chốt 16/11: 0,25 %** (rủi ro thật gồm spread + trượt giá + phí) |
| 5. Tính lot | Công thức 5.2 + 3.5, làm tròn xuống | 2 | đã có công thức |
| 6. Chuẩn SL | SL theo cấu trúc / ATR — văn bản chiến lược; Risk chặn SL quá gần (stops level) | 2e, 7 | STR-06 |
| 7. RR tối thiểu | Risk từ chối intent có TP / SL dưới mức tối thiểu (intent không có TP → theo chiến lược) | 4 | **H2 chốt 16/11: 1 : 1,5 sau chi phí** (lời = \|TP − vào\| × cỡ HĐ − spread − phí; lỗ = rủi ro / lot RSK-11) |
| 8. Trần heat (tổng rủi ro mở) | RSK-04, mọi lệnh vàng cùng chiều = một vị thế | 4 | H3 |
| 9. Giới hạn lỗ ngày / tuần / tháng + chuỗi thua | RSK-05, mốc reset + múi giờ | 4 | H4 |
| 10. Số lệnh tối đa / ngày | RSK-05 | 4 | H5 |
| 11. Bậc thang drawdown + dừng hẳn | RSK-05; dừng hẳn → Safety `PAUSED`, chỉ người mở lại | 4 | H6 |
| 12. Quy tắc tin tức | Đã có làn nhanh DEC-20 (chặn quanh tin) + Risk Q1; thêm: có giữ lệnh qua tin không | 4–5 | H7 |
| 13. Cuối tuần | 5-C07: cấm / cho kèm kiểm tra gap (7.6) | 5 | H8 |
| 14. Trần đòn bẩy thực tế | Bước 5 | 5 | H9 |
| 15. Chu kỳ rà soát / đổi tham số | Hồ sơ có phiên bản; USER tự đổi, hiệu lực ngay (Q6 = B) | 3 | Q6 ✓ |
| 16. Rút / nạp | Rủi ro tính theo equity lúc quyết; nạp / rút lớn → ghi sự kiện, đỉnh drawdown điều chỉnh theo luật viết sẵn (13.3–13.4: không nạp để gỡ) | 4 | H10 |
| 17. Ngắt "tilt" | Hệ thống tự động không có cảm xúc; thay bằng: người dùng **không** được nới hạn mức giữa phiên (chỉ ADMIN, có audit) | 3 | — |
| 18. Điều kiện dừng toàn bộ | Gộp vào mục 11 (drawdown dừng hẳn) | 4 | H6 |
| Chương 8 (bình quân giá lỗ, martingale) | Đề xuất **cấm cứng** thêm lệnh cùng chiều khi lệnh đang mở còn lỗ | 4 | H11 |

Không áp dụng: chương 9 (tâm lý — hệ thống tự động), 13.6 (quỹ / prop firm), 13.7 (thuế). Chương 12 (nhật ký, đo lường) → sổ cái + audit ở bước 6–7, chỉ số hiệu suất ở GĐ10. Phụ lục C (Monte Carlo) → tham khảo cho báo cáo khả thi / GĐ6. Phụ lục E (checklist trước lệnh, mục 5.5 "7 bước") → đối chiếu với thứ tự kiểm của Risk trong thiết kế 35.

Bước 0–2 chỉ cần Q1–Q5; bước 3 trở đi làm được phần cấu trúc trước khi có số (KN-12), Risk từ chối mọi intent tới khi có hồ sơ.

## Kiểm trên máy người dùng (điền chi tiết khi tới)

- Chỉ sau khi người dùng chọn lịch dựng lại (sau Gate GĐ1 + GĐ2 và sau khi nhánh chờ lên `develop`). Không dựng lại trong đợt đếm 5 ngày, không trong khung công bố tin.
- Dự kiến: `cli kha-thi` (chỉ đọc) trên dữ liệu thật; trang Rủi ro hiện "Chưa có hồ sơ rủi ro — mọi lệnh bị từ chối" khi chưa nhập; sau khi nhập hồ sơ: quyết định Risk paper có lý do tiếng Việt, **không có lệnh nào xuất hiện trong MT5**.

## Nhật ký kế hoạch

- **2026-11-16** — Viết bản nháp kế hoạch (chưa code). RSK-10, RSK-11 đặt đầu tiên (bước 1–2) theo DEC-28; ghi chú KN-14 (15 phút) đưa vào bước 1 (Q1); số rủi ro chờ KN-12; KN-07, KN-08 cuối GĐ5 (bước 9). Phát hiện khi đọc code: thông số broker KN-05 **không có giá trị tick và phí hoa hồng** → Q2, Q3; `RiskPolicy` đang có số rủi ro đặt sẵn trong code (0,5 % / 2 %) → bước 3 bỏ số mặc định. Chốt Q1 (Risk tự kiểm nguồn lịch), Q2 (USD trước, giá trị tick sau). Người dùng gửi tài liệu Quản lý vốn → thêm mục "Áp dụng tài liệu Quản lý vốn" (mẫu 18 mục → hồ sơ rủi ro, H1–H11 hỏi khi tới bước 3), bổ sung bước 4 (lỗ tháng, số lệnh / ngày, bậc thang drawdown, heat, cấm bình quân giá lỗ, kiểm tra gap) và bước 5 (trần đòn bẩy thực tế). Chốt Q3 (phí / lot nhập tay; chưa nhập → từ chối), Q4 (đệm trượt giá = spread xấu p95 30 ngày của chính sàn), Q5 (từ chối khi spread > cùng mốc p95 đó), Q6 (USER tự quyết hồ sơ rủi ro, ADMIN không can dự; lot tự theo equity), Q7 (người phát triển soạn nháp chiến lược v1, có phiên bản). **Đủ Q1–Q7**; còn H1–H11 (số hồ sơ rủi ro) hỏi ở bước 3. **Người dùng duyệt kế hoạch 16/11**, chọn code bước 0–2 ở phiên chat mới. Kế hoạch nằm ở nhánh `claude/inspiring-euler-xn2a7r` (chưa có ở nhánh chờ) → nhánh code GĐ5 tách từ `claude/affectionate-einstein-8ypy59` rồi gộp nhánh kế hoạch vào.

- **2026-11-16 (phiên code)** — Bước 0–2 xong trên nhánh `claude/fervent-hypatia-n3uyfn`: thiết kế 35; RSK-10 (Risk tự đọc cổng thật, Q1); RSK-11 2a–2e (thông số `spec_at` phải trùng nhịp tim, equity từ nhịp tim, spread + đệm p95 30 ngày + phí nhập tay, ngưỡng spread p95, stops / freeze level; `Decimal`); bảng phí `account_commissions` (migration 0024 — cách nhập ở bước 8, tới lúc đó Risk từ chối `COMMISSION_UNKNOWN`). Chi tiết: nhật ký GĐ5.

- **2026-11-16** — Bắt đầu bước 3: **H1 chốt 0,25 %/lệnh** (mức thấp nhất của DEC-09; người dùng chọn theo khuyến nghị — hệ thống chưa kiểm chứng). Lưu vào hồ sơ rủi ro khi có bảng `risk_profiles`; người dùng đổi được sau, luôn trong 0,25–0,5 %. Tiếp: H2 (R:R tối thiểu).
- **2026-11-16** — **H2 chốt R:R tối thiểu 1 : 1,5, tính sau chi phí** (người dùng chọn 1,5 thay vì khuyến nghị 1 : 2 — chấp nhận cần tỷ lệ thắng ≈ 40 % để hòa vốn, đổi lấy nhiều lệnh hơn). Lời trừ spread + phí; lỗ = rủi ro / lot đã gồm spread + đệm trượt giá + phí. Tiếp: H3 (trần tổng rủi ro mở — heat).

## Prompt cho phiên mới
Code GĐ5 bước 0–2 (RSK-10, RSK-11) — kế hoạch đã được người dùng duyệt 16/11, Q1–Q7 đã chốt (không hỏi lại). Đầu tiên: `git fetch origin claude/affectionate-einstein-8ypy59 claude/inspiring-euler-xn2a7r`, tạo nhánh GĐ5 từ `origin/claude/affectionate-einstein-8ypy59` (có KN-03 spread theo phút, KN-05 `spec_at`, KN-21) rồi gộp `origin/claude/inspiring-euler-xn2a7r` (chứa kế hoạch này, chỉ tài liệu). Sau đó đọc CLAUDE.md, PROGRESS.md, docs/ke-hoach/GD5-ke-hoach.md (bước 0–2 + bảng câu hỏi Q1–Q5) và chỉ các mục liên quan của docs/giai-doan/GD5-ke-hoach-giao-dich.md. GĐ5 làm song song (DEC-28): không đóng trước GĐ1 → GĐ4; kiểm trên máy GĐ1/GĐ2 (docs/ke-hoach/lich-kiem-tren-may.md) ưu tiên; không có lệnh thật nào; không tự đặt số rủi ro (hồ sơ rủi ro là bước 3 — H1–H11; ở bước 0–2 test dùng số giả có nhãn "chỉ để test"). Chưa lên develop. Làm theo thứ tự: bước 0 (mốc test + thiết kế 35) → bước 1 RSK-10 → bước 2 RSK-11 (2a–2e). Quy trình: thiết kế → code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick ở cả hai file, ghi nhật ký → chạy test + ruff, kiểm mã thoát thật → commit (nhắc mã việc) → push nhánh GĐ5 → kiểm CI. Người dùng không rành kỹ thuật: tiếng Việt đơn giản, mỗi lần hỏi một câu kèm 2–3 lựa chọn + khuyến nghị. Không bao giờ yêu cầu dán mật khẩu / token / khóa API vào chat.
