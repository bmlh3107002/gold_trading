# Kế hoạch GĐ1 — Dữ liệu vào (checklist dùng cho các phiên chat)

> Tạo 2026-11-07. Dùng file này để **bắt đầu và theo dõi** GĐ1 qua nhiều phiên chat. Chi tiết từng mã việc/case nằm ở [`docs/giai-doan/GD1-du-lieu-vao.md`](../giai-doan/GD1-du-lieu-vao.md) (nguồn sự thật về trạng thái `[ ]/[~]/[x]`); file này là **thứ tự làm + checklist**. Khi xong một bước: tick ở đây **và** đổi trạng thái + ghi nhật ký trong file GĐ1.

---

## Prompt dán vào phiên chat mới

> Đọc `CLAUDE.md`, `PROGRESS.md` (đã nạp sẵn), rồi `docs/ke-hoach/GD1-ke-hoach.md` (kế hoạch + checklist) và **chỉ** các mục liên quan của `docs/giai-doan/GD1-du-lieu-vao.md`. Tìm bước đầu tiên còn `[ ]` trong mục "Thứ tự làm" và làm **đúng bước đó**: code + test (gồm trường hợp xấu) + soát lại bằng kịch bản riêng → tick checklist ở cả hai file, ghi nhật ký GĐ1, cập nhật `PROGRESS.md` ngắn gọn → chạy `uv run pytest`, `uv run ruff check .` (và `npm run check && npm run build` nếu sửa frontend) → commit (nhắc mã việc) → push `develop`. Bước nào cần thao tác trên máy Windows thì hướng dẫn tôi **từng lệnh một**, chờ tôi trả lời. Tôi không rành kỹ thuật: giải thích tiếng Việt đơn giản, mỗi lần hỏi một câu. Không bao giờ yêu cầu dán mật khẩu/token/khóa API vào chat.

---

## Kiểm trên máy khi người dùng về (gom lại, làm theo thứ tự)

> Người dùng vắng máy Windows từ 2026-11-10 và đồng ý làm tiếp các bước rồi kiểm sau. Mỗi bước code xong mà chưa kiểm ghi ở đây. Khi kiểm: hướng dẫn **từng lệnh một**. Lỗi ở mục trên thì sửa trước rồi mới kiểm mục dưới.

1. **Cập nhật cùng lúc** backend + frontend (`docker compose build --no-cache backend frontend` → `docker compose up -d`) **và** Gateway (tải ZIP `develop`, chép đè `mt5_gateway\src`). Từ MT-14, Gateway < 0.4.0 không ghi được nến.
2. **MT-13:** `uv run mt5-gateway check` → bước "Liên kết MT5" báo cảnh báo "chưa liên kết" (vẫn SẴN SÀNG) → `run` → Gateway in `Chưa gửi nến: MT5_LINK_REQUIRED` và không thoát → web, trang Tài khoản, thẻ "Liên kết MT5" hiện MetaQuotes-Demo "chờ xác nhận" → gõ lại login → "Đã liên kết" → khoảng 30 s sau Gateway nạp bù, trang Thị trường có nến mới.
3. **MT-14:** trong MT5 đăng nhập một tài khoản demo khác (hoặc đăng xuất) → thẻ "Liên kết MT5" hiện băng đỏ, Gateway in `MT5_LINK_MISMATCH`, không có nến mới → đăng nhập lại tài khoản cũ → gõ login → "Xác minh lại" → nến chạy tiếp. Đăng xuất / đăng nhập lại đúng tài khoản → tự chạy lại.

## Việc còn treo trước khi bắt đầu bước 1

- [x] **Người dùng:** trả token của **Lord Trade** vào `gateway.env` (2026-11-07: Gateway mới `check` SẴN SÀNG, nạp nến được) (nếu đã thay bằng token tài khoản khác) → Gateway `check` mục 9 đạt, có nến mới.
- [x] **Người dùng:** build lại theo DEC-17 (2026-11-07) (`docker compose build --no-cache backend frontend` → `docker compose up -d`), xác nhận:
  - [x] log backend có dòng "bỏ tài khoản thừa u-user_cutlot (giữ default)" (2026-11-07, thu hồi 1 token)
  - [x] trang Quản trị: **một người một dòng**, nút Cấp token / Sửa / Khóa / Đặt lại mật khẩu / Xóa
  - [x] USER bấm "Xin cấp token" → ADMIN thấy yêu cầu → Cấp hoặc Từ chối (thử nhánh Từ chối để giữ token đang chạy; nhánh Cấp đã có e2e trong CI)
- [x] **Người dùng chốt thứ tự (2026-11-07):** giữ **thứ tự đề xuất** bên dưới, bắt đầu từ bước 1 (khung H1/H4/D1). Không đưa bước 4 lên đầu.

## Quyết định đã chốt (không hỏi lại)

| Mã | Lựa chọn |
| --- | --- |
| DEC-06 | 0 đồng — chỉ nguồn miễn phí |
| DEC-01 | Lịch + số actual từ BLS / BEA / Fed. **Không có forecast** → phần "bất ngờ" ghi "không đủ dữ liệu" |
| DEC-02 | Tin chỉ từ thông cáo chính thức (RSS Fed, Bộ Tài chính, BLS). **Danh sách nguồn cấu hình được** (thêm/bật/tắt không sửa code) |
| DEC-03 | Chỉ số USD **tự tính** từ 6 cặp trên MT5 (EURUSD, USDJPY, GBPUSD, USDCAD, USDSEK, USDCHF); nhãn "chỉ số USD tự tính", không gọi là DXY |
| DEC-04 | Proxy kỳ vọng Fed = lợi suất 2 năm so với lãi suất Fed (FRED). Không gọi là "xác suất" |
| DEC-05 | Chỉ ETF (GLD, IAU). NHTW **hoãn** (ING-29) |
| DEC-07 | Khóa miễn phí FRED + BLS + BEA — người dùng tự đăng ký khi tới bước 8/9, khóa chỉ trong `.env` |
| DEC-14 | Mỗi tài khoản phân tích theo **giá broker của chính mình**; không trộn giá giữa broker |
| DEC-17 | Quản trị: một USER một dòng; USER xin token, ADMIN cấp (token hiện cho ADMIN) |
| Sao lưu | Không sao lưu thủ công trong lúc phát triển; chỉ khi chạy thật |

---

## Thứ tự làm (mỗi bước: xong + test + kiểm chứng rồi mới sang bước sau)

### Bước 1 — Khung H1, H4, D1 (giá MT5)
- [x] ING-14: Gateway đọc + gửi H1/H4/D1 (vẫn chỉ đọc), backend nạp qua `CandleIngestor` (2026-11-07)
- [x] 1A-C19: nến D1/H4 lưu đúng `open_time` theo giờ server broker, **không** tự ghép từ M15
- [x] Test: DST, cuối tuần, nến chưa đóng, trùng/khác giá, thiếu nến
- [x] Kiểm trên máy người dùng: có nến H1/H4/D1 thật từ MetaQuotes-Demo (2026-11-07: 2.000/1.000/500 nến, 0 cách ly, giờ mở đúng giờ server)

### Bước 2 — Lịch ngày lễ (1B)
- [x] CAL-03: bảng ngày lễ/đóng sớm Mỹ có phiên bản, ghi nguồn (2026-11-07)
- [x] CAL-04: dùng `MarketCalendar` cho cờ `GAP` lúc nạp và R1 (2026-11-07)
- [x] CAL-05: thông báo đổi giờ đặc biệt của broker (cập nhật tay, có phiên bản) (2026-11-07)
- [x] 1B-C01..C04: đóng sớm không bị coi là thiếu nến; lễ rơi cuối tuần; broker lệch bảng → `CALENDAR_MISMATCH`; Giáng sinh–năm mới gắn cờ thanh khoản thấp (2026-11-07)
- [x] Người dùng: build lại `backend frontend` (2026-11-07: log backend có `lễ [us-holidays-2026.11.07] ∩ broker [Mon-Fri 00:00-23:00, Europe/Athens]`)
- [ ] Sau Lễ Tạ ơn 26–27/11: đối chiếu giờ broker thật với bảng (lệch → `GT_BROKER_SPECIAL_HOURS`). Không chặn bước 3

### Bước 3 — Nến cuối tuần bị giữ tới thứ Hai (1A-C21)
- [x] Coi nến đã đóng khi `open + khung ≤ giờ server` **và** lịch broker báo đóng cửa (2026-11-07: Gateway gửi vị trí 0 trong `tail_bar`, backend quyết: hết giờ nến + 2 phút **và** lịch đóng suốt từ lúc nến hết giờ)
- [x] Test: DST, cuối tuần, ngày lễ, nghỉ giữa phiên (2026-11-07)
- [x] Kiểm trên máy người dùng: tối thứ Sáu thấy nến cuối tuần (không chờ thứ Hai) (2026-11-07, thứ Bảy: nến cuối thứ Sáu M15/H1/H4/D1 vào ngay khi chạy Gateway mới, 0 cách ly. Theo dõi thêm: thứ Hai log không có "sửa" cho các nến này)

### Bước 4 — Mỗi tài khoản dùng MT5 của mình (đa tài khoản, DEC-14)
- [x] MT-12 + GW-09: Gateway báo danh tính terminal (login, server, company, DEMO/REAL, đường dẫn) + đọc tài khoản (equity, margin, đòn bẩy) và symbol (stops/freeze level, swap) (2026-11-07, Gateway 0.3.0; trang Tài khoản hiện thẻ "MT5 đang kết nối")
  - [x] Kiểm trên máy người dùng: cập nhật Gateway + build lại `backend frontend` → trang Tài khoản thấy đúng login/server MetaQuotes-Demo (2026-11-07)
- [x] MT-13: liên kết MT5 (`mt5_links`), USER xác nhận "login X / server Y" → ACTIVE; một `(login, server)` không ACTIVE ở 2 tài khoản (MT-C11) (2026-11-07: code + test, migration 0008; thẻ "Liên kết MT5" trên trang Tài khoản)
  - [ ] Kiểm trên máy người dùng: build lại `backend frontend` → trang Tài khoản thấy MT5 "chờ xác nhận" → gõ lại login → "Đã liên kết"
- [x] MT-14 + ING-15: phát hiện đổi tài khoản/broker/symbol → MISMATCH, chặn ghi, cảnh báo, không tự chuyển (MT-C08, MT-C14, 1A-C11) (2026-11-11: code + test, Gateway 0.4.0; phần đổi symbol chuyển sang MT-05. Chờ kiểm trên máy)
- [ ] MT-05: nguồn giá theo `(server, symbol)`; cùng server dùng chung; analyst chạy theo từng nguồn; bỏ khái niệm "nguồn giá chung" duy nhất
- [ ] MT-15: nhiều terminal MT5 trên một máy Windows, mỗi terminal một token (mong muốn: một Gateway quản lý nhiều terminal)
- [ ] Kiểm trên máy người dùng: tài khoản thứ hai có Gateway + MT5 riêng, ghi được nến của nguồn riêng, không ảnh hưởng Lord Trade

### Bước 5 — Giá sống bid/ask/spread
- [ ] GW-08: Gateway gửi tick/bid/ask/spread (chỉ đọc); thêm 6 cặp tiền cho chỉ số USD (chuẩn bị ING-24)
- [ ] ING-08: lưu gọn point-in-time (lấy mẫu/tổng hợp theo giây), có chính sách giữ dữ liệu
- [ ] 1A-C13 (tick lỗi/đảo thứ tự), 1A-C14 (`WIDE_SPREAD`), 1A-C15 (tick khi lịch đóng cửa), 1A-C08 (broker đổi múi giờ khi đang chạy)
- [ ] DSH-07: hiển thị bid/ask/spread trên web

### Bước 6 — Gateway bền vững
- [ ] GW-06: chạy như dịch vụ Windows, tự khởi động cùng máy
- [ ] GW-07: hàng đợi trên đĩa + tự nạp bù khi gián đoạn dài (1A-C09)
- [ ] ING-16: phát hiện lệch đồng hồ Gateway ↔ backend ↔ server MT5 (1A-C20)
- [ ] 1A-C10: mất kết nối → STALE sau 30 s, Dashboard báo

### Bước 7 — Khung chung cho nguồn ngoài (1G)
- [ ] DB-08: bảng lịch kinh tế / tin / series vĩ mô (append-only, point-in-time) — migration mới
- [ ] ING-13: store point-in-time dùng chung (tái dùng `ingestion/point_in_time.py` hoặc thay)
- [ ] ING-30: trạng thái HEALTHY/STALE/MISSING/INVALID, TTL riêng từng nguồn
- [ ] ING-31: khóa API chỉ trong `.env`, không commit, không log
- [ ] ING-32: ghi giấy phép/điều khoản từng nguồn ở `docs/thiet-ke/`

### Bước 8 — Lịch kinh tế (1C) ← hướng dẫn đăng ký khóa **BLS**, **BEA**
- [ ] Người dùng đăng ký khóa BLS, BEA (từng khóa một), dán vào `.env` trên máy
- [ ] ING-09: lịch công bố (CPI, NFP, FOMC, PCE, GDP, PPI, bán lẻ, thất nghiệp tuần) vài tháng tới, `releaseAt` UTC
- [ ] ING-17: số actual ngay khi công bố, đo độ trễ
- [ ] ING-18: forecast → **không đủ dữ liệu** (DEC-01); `previous` nếu nguồn chính thức có
- [ ] ING-19 (revision), ING-20 (mức quan trọng có phiên bản)
- [ ] 1C-C01..C08 (chưa công bố vs 0, hoãn/hủy, đổi giờ, DST Mỹ, nguồn chết lúc công bố → kéo dài cửa sổ chặn, trùng nguồn, không forecast, sửa số lớn)
- [ ] Bật chạy sớm trên máy người dùng để kịp bắt một lần CPI/NFP thật

### Bước 9 — Vĩ mô + dòng tiền (1E + 1F) ← hướng dẫn đăng ký khóa **FRED**
- [ ] Người dùng đăng ký khóa FRED, dán vào `.env`
- [ ] ING-11: khung series vĩ mô theo `releaseAt` (point-in-time, revision)
- [ ] ING-25 (lợi suất thực 10 năm), ING-26 (lợi suất 2 năm, 10 năm), ING-27 (proxy Fed, DEC-04)
- [ ] ING-24: chỉ số USD tự tính (DEC-03); thiếu cặp / lệch thời điểm → không đủ dữ liệu
- [ ] 1E-C01..C05 (công bố D+1, giá trị ".", series ngừng, đổi đơn vị, khóa hết hạn — không lộ khóa)
- [ ] ING-12: COT vàng (`available_at` = thứ Sáu công bố)
- [ ] ING-28: ETF GLD, IAU (kiểm điều khoản tải trước khi bật)
- [ ] 1F-C01..C03
- [ ] ING-29 NHTW: **hoãn** (không làm)

### Bước 10 — Tin tức (1D) + hoàn thiện
- [ ] ING-10: khung nạp tin (fingerprint, `publishedAt` + `ingestedAt`, URL, nội dung gốc), **danh sách nguồn cấu hình được**
- [ ] ING-21: RSS Fed, Bộ Tài chính, BLS
- [ ] ING-22: nguồn tin tổng hợp — **không làm** (DEC-02), chỉ cần khung cho phép thêm sau
- [ ] ING-23: nhận diện ngôn ngữ + thực thể cơ bản
- [ ] 1D-C01..C06 (trùng nguồn, sửa bài, sai giờ, nội dung độc hại **không bao giờ thực thi**, nguồn chết, tin cũ đăng lại)
- [ ] DSH-09: trang "Nguồn dữ liệu" (trạng thái, lần nhận cuối, độ trễ, số cách ly)
- [ ] ING-33: chính sách giữ dữ liệu + ước tính dung lượng
- [ ] ING-34: test replay mọi nguồn (nạp lại → cùng kết quả)

---

## Gate GĐ1 (đủ hết mới đóng; người dùng xác nhận)

- [ ] Mọi việc 1A–1G xong (trừ việc người dùng hoãn: ING-29), mọi case có test
- [ ] MT-12..MT-15 + case MT-C08, MT-C11, MT-C14 (phần dữ liệu) xong
- [ ] Chạy trên máy người dùng **≥ 5 ngày giao dịch liên tục**
- [ ] Bắt được **ít nhất một lần công bố lớn** (CPI hoặc NFP): đúng giờ, đúng actual
- [ ] Trang Nguồn dữ liệu hiển thị đủ
- [ ] Bản sao lưu **tự động** có dữ liệu mới (không cần sao lưu thủ công)
- [ ] Người dùng xác nhận đóng GĐ1 → chuyển GĐ2

## Bất biến (mọi bước)

Point-in-time (`available_at <= as_of`), UTC, chỉ nến đã đóng, `SAMPLE` không dẫn tới SHADOW/LIVE, thiếu dữ liệu → "không đủ dữ liệu", MT5 Gateway **chỉ đọc**, mỗi thay đổi có test (gồm trường hợp xấu), không bịa số liệu, không mở rộng phạm vi, đổi schema = migration mới.
