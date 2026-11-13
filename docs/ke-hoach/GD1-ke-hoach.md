# Kế hoạch GĐ1 — Dữ liệu vào (checklist dùng cho các phiên chat)

> Tạo 2026-11-07. Dùng file này để **bắt đầu và theo dõi** GĐ1 qua nhiều phiên chat. Chi tiết từng mã việc/case nằm ở [`docs/giai-doan/GD1-du-lieu-vao.md`](../giai-doan/GD1-du-lieu-vao.md) (nguồn sự thật về trạng thái `[ ]/[~]/[x]`); file này là **thứ tự làm + checklist**. Khi xong một bước: tick ở đây **và** đổi trạng thái + ghi nhật ký trong file GĐ1.

---

## Prompt dán vào phiên chat mới

> Đọc `CLAUDE.md`, `PROGRESS.md` (đã nạp sẵn), rồi `docs/ke-hoach/GD1-ke-hoach.md` (kế hoạch + checklist) và **chỉ** các mục liên quan của `docs/giai-doan/GD1-du-lieu-vao.md`. Tìm bước đầu tiên còn `[ ]` trong mục "Thứ tự làm" và làm **đúng bước đó**: code + test (gồm trường hợp xấu) + soát lại bằng kịch bản riêng → tick checklist ở cả hai file, ghi nhật ký GĐ1, cập nhật `PROGRESS.md` ngắn gọn → chạy `uv run pytest`, `uv run ruff check .` (và `npm run check && npm run build` nếu sửa frontend) → commit (nhắc mã việc) → push `develop`. Bước nào cần thao tác trên máy Windows thì hướng dẫn tôi **từng lệnh một**, chờ tôi trả lời. Tôi không rành kỹ thuật: giải thích tiếng Việt đơn giản, mỗi lần hỏi một câu. Không bao giờ yêu cầu dán mật khẩu/token/khóa API vào chat.

---

## Kiểm trên máy khi người dùng về (gom lại, làm theo thứ tự)

> **Tiến độ 2026-11-12:** mục 1, 2, 3, 4, 5, 7, 9, 10 ĐẠT; mục 6 đạt phần lưu + báo cũ; mục 8 đạt 6b + 6c, **còn 6a** (dừng backend qua đêm > 5 giờ). Máy người dùng chạy `run-all` 2 MT5 (lordtrade + taikhoan2).
> **2026-11-13:** 6a lần 1 không hợp lệ (Gateway bị tắt lúc 23:57, không chạy qua đêm). **Làm lại tối 13/11:** trước khi ngủ kiểm Gateway đang chạy (`Get-Process python`), rồi `docker compose stop backend`; sáng hôm sau `docker compose start backend` → xem `logs\lordtrade.log` + `logs\taikhoan2.log` (`Get-Content … -Tail 40 -Encoding UTF8`) có "Nạp bù sau gián đoạn", biểu đồ không hở. Hai điểm cần theo dõi (Gateway chạy trùng giữa hai chế độ; Task Scheduler không tự chạy lại khi bị tắt): nhật ký GĐ1 ngày 2026-11-13. Điểm cần cải thiện (a)–(f): nhật ký GĐ1 ngày 2026-11-12.

> Người dùng vắng máy Windows từ 2026-11-10 và đồng ý làm tiếp các bước rồi kiểm sau. Mỗi bước code xong mà chưa kiểm ghi ở đây. Khi kiểm: hướng dẫn **từng lệnh một**. Lỗi ở mục trên thì sửa trước rồi mới kiểm mục dưới.

1. **Cập nhật cùng lúc** backend + frontend (`docker compose build --no-cache backend frontend` → `docker compose up -d`) **và** Gateway (tải ZIP `develop`, chép đè `mt5_gateway\src`). Từ MT-14, Gateway < 0.4.0 không ghi được nến. **Khi `deploy/docker-compose.yml` đổi (vd. thêm biến khóa API) phải tải lại file này** (`curl.exe -fsSLO https://raw.githubusercontent.com/bmlh3107002/gold_trading/develop/deploy/docker-compose.yml`, sao lưu bản cũ trước) — `build` không tự cập nhật nó (bài học 2026-11-13). Bản Gateway mới nhất: 0.10.3 (sửa 8 điểm cải thiện 2026-11-12; cần dựng lại backend + frontend cùng lúc). (2026-11-12: backend + DB lên 0012 đạt; Gateway mới `check` SẴN SÀNG; sửa `localhost` chậm 2 s → 0.10.1, cần tải lại Gateway.)
2. **MT-13:** `uv run mt5-gateway check` → bước "Liên kết MT5" báo cảnh báo "chưa liên kết" (vẫn SẴN SÀNG) → `run` → Gateway in `Chưa gửi nến: MT5_LINK_REQUIRED` và không thoát → web, trang Tài khoản, thẻ "Liên kết MT5" hiện MetaQuotes-Demo "chờ xác nhận" → gõ lại login → "Đã liên kết" → khoảng 30 s sau Gateway nạp bù, trang Thị trường có nến mới.
3. **MT-05:** sau khi cập nhật, log backend không lỗi migration 0009 + 0010 (TimescaleDB thật: đổi khóa chính hypertable); trang Thị trường **trống** cho tới khi liên kết (nến cũ đã tách thành legacy) → sau khi xác nhận liên kết, Gateway nạp lại, trang Thị trường có nến; thẻ "Liên kết MT5" hiện symbol broker `XAUUSD`; giá ở header và trang Thị trường hiện bình thường; khoảng 15 giây sau thẻ Phân tích kỹ thuật có kết quả; đăng nhập ADMIN không thấy giá.
4. **MT-14:** trong MT5 đăng nhập một tài khoản demo khác (hoặc đăng xuất) → thẻ "Liên kết MT5" hiện băng đỏ, Gateway in `MT5_LINK_MISMATCH`, không có nến mới → đăng nhập lại tài khoản cũ → gõ login → "Xác minh lại" → nến chạy tiếp. Đăng xuất / đăng nhập lại đúng tài khoản → tự chạy lại.
5. **MT-15:** (a) máy một MT5: `check` dòng "Kết nối MT5" hiện thư mục MT5 nếu đã đặt `GT_MT5_PATH`; (b) khi có MT5 thứ hai (cài thư mục riêng, tài khoản thứ hai): tạo `terminals\lordtrade.env` + `terminals\<tên>.env` theo README mục "Nhiều MT5 trên một máy" → `check-all` cả hai SẴN SÀNG → `run-all` → mỗi người xác nhận liên kết trên trang Tài khoản của mình → mỗi người thấy giá broker mình; thử cố ý chép cùng token sang hai file → `run-all` từ chối, không chạy MT5 nào.
6. **Bước 5a + 5b (giá sống):** log backend không lỗi migration 0011 (TimescaleDB thật: hypertable `quote_seconds`); `check` dòng "Giá sống (bid/ask)" ĐẠT khi thị trường mở (CẢNH BÁO "tick sai khoảng thời gian" → gửi lại kết quả check, đây là điểm chưa kiểm được với MT5 thật); `run` không có log `Tắt gửi giá sống`; sau vài phút đếm dòng: `docker compose exec db psql -U gold -d gold_trading -c "select count(*), max(t) from quote_seconds"` (mặc định; nếu `.env` đặt `POSTGRES_USER`/`POSTGRES_DB` khác thì dùng tên đó) → số tăng dần, `max(t)` cách giờ UTC hiện tại vài giây; trang Thị trường thẻ "Giá sống" hiện "Đang cập nhật", bid/ask khớp Market Watch của MT5 (trễ vài giây), spread khớp; tắt Gateway ~20 giây khi thị trường mở → thẻ báo đỏ "Giá sống đã cũ".
7. **Bước 5d (6 cặp tiền):** `check` dòng "Cặp tiền chỉ số USD" — ghi lại có mấy cặp / thiếu cặp nào (nếu thiếu: Market Watch → Show All rồi `check` lại; tên khác thì đặt `GT_USD_PAIRS`). Sau vài phút `run`: `docker compose exec db psql -U gold -d gold_trading -c "select symbol, count(*), max(open_time) from candles where symbol <> 'XAUUSD' group by symbol"` → mỗi cặp có nến, giờ mới nhất gần hiện tại.
8. **Bước 6a + 6b:** `check` có dòng "Đồng hồ máy" ĐẠT (nếu CẢNH BÁO: bật đồng bộ giờ Windows rồi `check` lại); trang Tài khoản thẻ MT5 hiện "Đồng hồ máy chạy Gateway: Khớp" và "Đồng hồ server MT5: Khớp". Thử gián đoạn: khi thị trường mở, `docker compose stop backend` **hơn 5 giờ** (Gateway luôn gửi lại 20 nến M15 = 5 giờ gần nhất, nên gián đoạn ngắn hơn không đi vào đường nạp bù dài; sửa 2026-11-12, trước ghi nhầm "1 giờ") rồi `docker compose start backend` → log Gateway có "Nạp bù sau gián đoạn: N nến M15", trang Thị trường không hở nến trong khoảng đó. **6c:** tắt cửa sổ Gateway → sau ~30 giây web hiện băng đỏ "Mất kết nối MT5" (lý do: không gửi tín hiệu); bật lại → hết băng. Rút mạng (hoặc tắt Wi-Fi) khi MT5 mở → băng đỏ lý do "MT5 mất kết nối tới máy chủ broker". Đăng xuất MT5 → lý do "chưa đăng nhập".
9. **Bước 6d (tự chạy):** đóng cửa sổ `run` → `powershell -ExecutionPolicy Bypass -File scripts\cai-tu-chay.ps1` (thêm `-NhieuMT5` nếu dùng `terminals`) → báo "ĐÃ CÀI"; mở `logs\gateway.log` thấy nạp bù + nến mới; web không có băng đỏ. Mở thêm `uv run mt5-gateway run` → báo "Đã có một Gateway khác đang chạy". Khởi động lại máy, đăng nhập, chờ 2 phút → web có giá mới mà không mở cửa sổ nào. Gỡ: `scripts\go-tu-chay.ps1`.
10. **Bước 7a + 7b:** sau khi cập nhật backend, log không lỗi migration 0012 + 0013 (`docker compose logs backend | findstr "0012 0013"` thấy dòng chạy, không có `Error`). Chưa có nguồn nào ghi vào bảng mới nên trên web chưa thấy gì khác. (7a đã đạt 2026-11-12; 0013 kiểm lần cập nhật sau.)
11. **Bước 8c (BEA):** người dùng đăng ký khóa BEA (miễn phí, `apps.bea.gov/api/signup/`, khóa gửi qua email, bấm link kích hoạt) → dán vào `.env` dòng `GT_BEA_API_KEY=` (không dán vào chat) → dựng lại `backend frontend` → `docker compose exec backend python -m gold_trading.ingestion.cli bea --dry-run` → thấy "Lịch BEA: OK", "Số actual BEA: OK", GDP 2026Q3 và PCE tháng gần nhất khớp trang BEA; chân trang web có câu "This product uses the Bureau of Economic Analysis (BEA) Data API…". **Kiểm trên máy 2026-11-13: đạt** — `bea --dry-run` với khóa thật: lịch OK 28 sự kiện, số actual OK 91 bản ghi (GDP 2026Q3 3.4, PCE 9/2026 0.5, PCE lõi 0.3, chỉ số PCE 132.257 — khớp file công khai của BEA); phản hồi GetData thật đọc đúng. Bài học: `docker-compose.yml` trên máy là bản cũ (trước 7c) nên khóa không vào container (`KEY_MISSING`) → tải lại file compose (bản cũ giữ ở `docker-compose.cu.yml`). Câu ghi nguồn BEA + Fed hiện ở chân trang web, không đè (người dùng xác nhận).
12. **Bước 8d (Census) — TẠM HOÃN 2026-11-13** (Census chặn truy cập từ Việt Nam: 403). Khi xem lại: người dùng đăng ký khóa Census (miễn phí, `api.census.gov/data/key_signup.html`, email đuôi .com/.net/.org/.gov/.edu, kích hoạt qua email) → thêm dòng `GT_CENSUS_API_KEY=` vào `.env` (không dán vào chat; kiểm bằng lệnh chỉ in tên biến + độ dài) → dựng lại `backend frontend` → `docker compose up -d` → `docker compose exec backend python -m gold_trading.ingestion.cli census --dry-run` → "Lịch Census: OK", "Số actual Census: OK", `44X72:SM` tháng gần nhất khớp trang `census.gov/retail`; chân trang web có câu Census. Lần công bố gần nhất: **17/11/2026 13:30 UTC** (số tháng 10).
13. **Bước 8f (DOL):** dựng lại `backend frontend` → `docker compose up -d` → `docker compose exec backend python -m gold_trading.ingestion.cli dol --dry-run` → "Lịch DOL (theo quy tắc): OK", "Số trợ cấp thất nghiệp DOL: OK", số `ICSA` tuần mới nhất khớp bản tin `dol.gov/ui/data.pdf`; chân trang web có dòng DOL. Thứ Năm 19/11/2026 sau 8:30 ET (20:30 giờ Việt Nam) chạy lại → thấy tuần đến 14/11, không cờ `RELEASE_OFF_SCHEDULE`. Đối chiếu bảng ngày lễ liên bang với trang OPM (người dùng chụp `opm.gov/policy-data-oversight/pay-leave/federal-holidays/`, năm 2026 + 2027).
14. **Bước 8g (chạy tự động + bảng lịch):** dựng lại `backend frontend` (gộp với mục 13) → `docker compose up -d` → chờ 1 phút → `docker compose logs backend | findstr "fed_fomc bea_ dol_claims"` → có dòng bật `fed_fomc, bea_schedule, dol_claims_schedule, bea_nipa, dol_claims` và mỗi nguồn một dòng `OK` (`bea_nipa` OK vì đã có khóa). `docker compose logs backend | findstr "api/data"` → **không** có dòng nào (URL có khóa). `docker compose exec backend python -m gold_trading.ingestion.cli lich --days 14` → 5 nguồn "khỏe", lịch 14 ngày có FOMC / BEA / DOL, giờ Việt Nam đúng (vd. DOL 19/11 20:30). `docker compose restart backend` → 2 phút sau log không có dòng `OK` mới (không tải lại dồn). Thứ Năm 19/11 sau 20:30 giờ Việt Nam: `cli lich` → dòng `CLAIMS:2026-11-19` có `số: RECEIVED ICSA=…` khớp `dol.gov/ui/data.pdf`.

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
| DEC-01 | Lịch + số actual từ BLS / BEA / Fed + **Census** (bán lẻ) + **DOL** (thất nghiệp tuần) — mỗi tin từ nơi phát hành gốc (bổ sung 2026-11-13). **Không có forecast** → phần "bất ngờ" ghi "không đủ dữ liệu" |
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
  - [x] Kiểm trên máy người dùng: build lại `backend frontend` → trang Tài khoản thấy MT5 "chờ xác nhận" → gõ lại login → "Đã liên kết" (2026-11-12: đạt, Gateway nạp bù 5.000/2.000/1.000/500 nến + 6 cặp tiền, 0 cách ly)
- [x] MT-14 + ING-15: phát hiện đổi tài khoản/broker/symbol → MISMATCH, chặn ghi, cảnh báo, không tự chuyển (MT-C08, MT-C14, 1A-C11) (2026-11-11: code + test, Gateway 0.4.0; phần đổi symbol chuyển sang MT-05. **Đã kiểm trên máy 2026-11-12: đạt**)
- [x] MT-05: nguồn giá theo `(server, symbol)`; cùng server dùng chung; analyst chạy theo từng nguồn; bỏ khái niệm "nguồn giá chung" duy nhất (2026-11-11: code + test, migration 0009 + 0010, Gateway 0.5.0; chờ kiểm trên máy)
  - [x] 4a lưu trữ: migration 0009, Gateway 0.5.0, symbol khóa vào liên kết, dữ liệu cũ → legacy (2026-11-11, chờ kiểm trên máy)
  - [x] 4b đọc: mỗi tài khoản xem giá + analyst theo nguồn của mình (2026-11-11, chờ kiểm trên máy)
- [x] MT-15: nhiều terminal MT5 trên một máy Windows, mỗi terminal một token (mong muốn: một Gateway quản lý nhiều terminal) (2026-11-12: code + test, Gateway 0.6.0 `run-all`; chờ kiểm trên máy)
- [x] Kiểm trên máy người dùng: tài khoản thứ hai có Gateway + MT5 riêng, ghi được nến của nguồn riêng, không ảnh hưởng Lord Trade (2026-11-12: đạt, `run-all` 2 MT5 cùng MetaQuotes-Demo → dùng chung feed; cấu hình trùng token/MT5 bị từ chối)

### Bước 5 — Giá sống bid/ask/spread
Chia 4 phần (2026-11-12):
- [x] 5a — ING-08 phía backend: lưu gọn point-in-time (gom theo giây), giữ `GT_QUOTE_RETENTION_DAYS`; 1A-C13 (backend kiểm lại), 1A-C14 (`WIDE_SPREAD`), 1A-C15 (`CALENDAR_CLOSED` / `CALENDAR_MISMATCH`) (2026-11-12: code + test, migration 0011; chờ kiểm trên máy)
- [x] 5b — GW-08: Gateway gom tick → gửi bid/ask/spread theo giây (chỉ đọc); 1A-C13 phía Gateway; 1A-C08 (broker đổi múi giờ khi đang chạy) (2026-11-12: code + test, Gateway 0.7.0; chờ kiểm trên máy)
- [x] 5c — DSH-07: hiển thị bid/ask/spread trên web (2026-11-12: code + test, thẻ "Giá sống" trang Thị trường; chờ kiểm trên máy)
- [x] 5d — thêm 6 cặp tiền cho chỉ số USD (chuẩn bị ING-24) (2026-11-12: code + test, Gateway 0.8.0, nến M15; chờ kiểm trên máy)

### Bước 6 — Gateway bền vững
Chia 4 phần (2026-11-12):
- [x] 6a — GW-07 + 1A-C09: tự nạp bù khi gián đoạn dài (lịch sử MT5 là hàng đợi bền vững) (2026-11-12: code + test, Gateway 0.8.1; chờ kiểm trên máy)
- [x] 6b — ING-16 + 1A-C20: phát hiện lệch đồng hồ Gateway ↔ backend ↔ server MT5 (phân biệt với broker đổi giờ) (2026-11-12: code + test, Gateway 0.9.0; chờ kiểm trên máy)
- [x] 6c — 1A-C10: mất kết nối → STALE sau 30 s, Dashboard báo (2026-11-12: code + test, băng đỏ mọi trang + lý do, Gateway 0.9.1; chờ kiểm trên máy)
- [x] 6d — GW-06: tự chạy cùng Windows, ghi log ra file (2026-11-12: code + test, Task Scheduler + `scripts/cai-tu-chay.ps1`, Gateway 0.10.0; chờ kiểm trên máy)

### Bước 7 — Khung chung cho nguồn ngoài (1G)
Chia 4 phần (2026-11-12), thiết kế ở `docs/thiet-ke/10-nguon-ngoai.md`:
- [x] 7a — DB-08 + ING-13: bảng `external_records` + `external_quarantine` (append-only, point-in-time, `known_at = max(ingested_at, available_at)`) — migration 0012; store SQL + bản trong bộ nhớ cùng quy tắc (2026-11-12: code + test, đã kiểm trên Postgres 16; TimescaleDB qua CI)
- [x] 7b — ING-30: trạng thái HEALTHY/STALE/MISSING/INVALID, TTL riêng từng nguồn (2026-11-13: code + test, migration 0013 `external_source_checks`, trạng thái tính lại tại mọi `as_of`; TTL cụ thể đặt khi thêm nguồn ở bước 8–10)
- [x] 7c — ING-31: khóa API chỉ trong `.env`, không commit, không log (2026-11-13: code + test, `ingestion/api_keys.py`, biến `GT_FRED/BLS/BEA_API_KEY` trong compose; người dùng chưa cần làm gì)
- [x] 7d — ING-32: ghi giấy phép/điều khoản từng nguồn ở `docs/thiet-ke/` (2026-11-13: `docs/thiet-ke/11-dieu-khoan-nguon.md` + khóa trong code: chỉ bật nguồn khi điều khoản `VERIFIED`; hiện tất cả `NEEDS_REVIEW`, IAU `BLOCKED` — chưa đọc được nguyên văn)

### Bước 8 — Lịch kinh tế (1C) ← hướng dẫn đăng ký khóa **BLS**, **BEA**
Chia nhỏ (2026-11-13), mỗi phần xong + test + kiểm rồi mới sang phần sau:
- [x] 8a — đọc nguyên văn điều khoản (người dùng cho phép tải trang chính thức, chỉ đọc): BEA, Census, Fed `VERIFIED`; GLD `BLOCKED`; FRED/BLS/CFTC/DOL/Bộ Tài chính chưa đọc được (chi tiết `docs/thiet-ke/11-dieu-khoan-nguon.md`). Thêm `GT_CENSUS_API_KEY` (Census bắt buộc khóa) (2026-11-13)
- [x] 8b — Fed: lịch họp FOMC (không cần khóa, điều khoản `VERIFIED`) — nguồn lịch đầu tiên đi qua cả khung 7a–7d (2026-11-13: `ingestion/sources/fed_fomc.py` + `calendar_sync.py`, thiết kế `docs/thiet-ke/12-lich-fomc.md`; lệnh `python -m gold_trading.ingestion.cli fomc`; chưa chạy tự động — 8g)
- [x] 8c — BEA: lịch + actual GDP, PCE (người dùng đăng ký khóa BEA; hiện câu ghi nguồn BEA trên web trước khi bật) (2026-11-13: `ingestion/sources/bea.py`, thiết kế `docs/thiet-ke/13-bea.md`; câu ghi nguồn BEA nguyên văn ở chân mọi trang; lệnh `python -m gold_trading.ingestion.cli bea`; đã đăng ký khóa + kiểm trên máy 2026-11-13: đạt (mục 11); chưa chạy tự động — 8g)
- [x] 8d — Census: lịch + actual bán lẻ (người dùng đăng ký khóa Census; hiện câu ghi nguồn Census trước khi bật) (2026-11-13: `ingestion/sources/census.py`, thiết kế `docs/thiet-ke/14-census.md`; câu ghi nguồn Census ở chân trang; lệnh `python -m gold_trading.ingestion.cli census`; **Census chặn mọi truy cập từ Việt Nam** (trang đăng ký khóa bị Cloudflare chặn cả Wi-Fi lẫn 4G; máy Windows: API và trang lịch đều 403) → **người dùng chọn tạm hoãn bán lẻ** 2026-11-13: không bật Census trên máy, không VPN lách; xem lại trước Gate GĐ1 — mục 12)
- [ ] 8e — BLS: CPI, NFP, PPI — trước hết đọc điều khoản BLS (trang web BLS chặn máy chủ đám mây → đọc trên máy người dùng hoặc cách khác), rồi khóa BLS. **Đang làm (2026-11-13, tạm dừng — người dùng ở công ty):** từ máy Windows: `api.bls.gov` **200** (API số liệu dùng được từ Việt Nam), `www.bls.gov` **403** với `curl` nhưng **trình duyệt vào được** → BLS chặn chương trình tự động, không chặn Việt Nam; lịch CPI thấy trên trình duyệt (vd. CPI tháng 11/2026 công bố 10/12/2026 08:30 ET). Không giả trình duyệt để lách. Điều khoản API (`/developers/termsOfService.htm`) mới đọc qua ảnh chụp: Scope, Secondary Use, một phần Citing Data (phải ghi ngày truy cập + câu "BLS.gov cannot vouch for the data or analyses derived from these data after the data have been retrieved from BLS.gov"; không dùng logo BLS — **đoạn này bị che một phần, cần chụp lại**), Public Participation. **Việc tiếp:** người dùng chụp lại đoạn Citing Data + phần còn lại của trang → quyết định cách lấy lịch (trang web chặn chương trình tự động) → đăng ký khóa BLS
- [x] 8f — DOL: trợ cấp thất nghiệp tuần (2026-11-13: `ingestion/sources/dol.py` + `market/federal_holidays.py`, thiết kế `docs/thiet-ke/15-dol.md`; số từ bản tin PDF `www.dol.gov/ui/data.pdf` — máy người dùng tải được (200); DOL không đăng lịch dạng đọc được → **người dùng chọn lịch theo quy tắc** thứ Năm 8:30 ET, tuần có ngày lễ liên bang chặn cả ngày thứ Tư–Sáu; điều khoản DOL `VERIFIED` cho bản tin PDF; ghi nguồn DOL ở chân trang; lệnh `python -m gold_trading.ingestion.cli dol`; **kiểm trên máy: mục 13**)
- [ ] 8g — ING-19, ING-20, các case 1C, bật chạy trên máy người dùng. Chia 4 phần (2026-11-13):
  - [x] 8g-1 — chạy tự động FOMC + BEA + DOL trong backend (`ingestion/external_runner.py`, thiết kế `docs/thiet-ke/16-chay-tu-dong-nguon-lich.md`; biến `GT_EXTERNAL_SOURCES`) (2026-11-13: code + test; chờ kiểm trên máy — mục 14)
  - [x] 8g-2 — ING-20 mức quan trọng có phiên bản + bảng lịch hợp nhất (1C-C07: không forecast → "không đủ dữ liệu") (2026-11-13: `ingestion/event_importance.py`, `ingestion/economic_calendar.py`, lệnh `cli lich`, thiết kế `docs/thiet-ke/17-lich-kinh-te-hop-nhat.md`)
  - [x] 8g-3 — 1C-C05 (nguồn chết lúc công bố → kéo dài cửa sổ, cảnh báo) + ING-19 / 1C-C08 (sửa số lớn → cờ) (2026-11-13: `economic_calendar.py` `actual_status` + `health_map`, `ingestion/revisions.py`; thiết kế `17-…` mục 4–5)
  - [ ] 8g-4 — bật chạy trên máy người dùng (dựng lại một lần, gộp kiểm mục 13 DOL + mục 14)
- [ ] Trước khi bật mỗi nguồn: **đọc nguyên văn điều khoản** (đường dẫn ở `docs/thiet-ke/11-dieu-khoan-nguon.md`) → `VERIFIED` (ING-32)
- [ ] Người dùng đăng ký khóa BLS, BEA, **Census** (bắt buộc khóa), DOL nếu cần (từng khóa một), dán vào `.env` trên máy; thêm `GT_CENSUS_API_KEY` (+ DOL) vào `KEY_ENV` + compose
- [ ] ING-09: lịch công bố (CPI, NFP, FOMC, PCE, GDP, PPI, bán lẻ, thất nghiệp tuần) vài tháng tới, `releaseAt` UTC; nguồn gốc: BLS, BEA, Fed, **Census** (bán lẻ), **DOL** (thất nghiệp tuần) — kiểm Census/DOL có cần khóa không
- [ ] ING-17: số actual ngay khi công bố, đo độ trễ
- [ ] ING-18: forecast → **không đủ dữ liệu** (DEC-01); `previous` nếu nguồn chính thức có
- [x] ING-19 (revision), ING-20 (mức quan trọng có phiên bản) — ING-20 xong 8g-2, ING-19 xong 8g-3
- [ ] 1C-C01..C08 (chưa công bố vs 0, hoãn/hủy, đổi giờ, DST Mỹ, nguồn chết lúc công bố → kéo dài cửa sổ chặn, trùng nguồn, không forecast, sửa số lớn)
- [ ] Bật chạy sớm trên máy người dùng để kịp bắt một lần CPI/NFP thật
- Việc để sau (không thuộc Gate GĐ1, người dùng đồng ý 2026-11-12): **nhập tay forecast** trước các kỳ công bố lớn. ForexFactory / Investing / FXStreet / Kitco không đưa vào GĐ1 (lý do ở ING-18 file GĐ1)

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
- [ ] **Doanh số bán lẻ (tạm hoãn 2026-11-13, Census chặn Việt Nam):** quyết định lại — lịch chép tay có phiên bản / số qua FRED (ngoại lệ DEC-01) / bỏ hẳn. Trong lúc hoãn **không có cửa sổ chặn quanh tin bán lẻ** → phải xử lý trước khi chạy SHADOW/LIVE
- [ ] MT-12..MT-15 + case MT-C08, MT-C11, MT-C14 (phần dữ liệu) xong
- [ ] Chạy trên máy người dùng **≥ 5 ngày giao dịch liên tục**
- [ ] Bắt được **ít nhất một lần công bố lớn** (CPI hoặc NFP): đúng giờ, đúng actual
- [ ] Trang Nguồn dữ liệu hiển thị đủ
- [ ] Bản sao lưu **tự động** có dữ liệu mới (không cần sao lưu thủ công)
- [ ] Người dùng xác nhận đóng GĐ1 → chuyển GĐ2

## Bất biến (mọi bước)

Point-in-time (`available_at <= as_of`), UTC, chỉ nến đã đóng, `SAMPLE` không dẫn tới SHADOW/LIVE, thiếu dữ liệu → "không đủ dữ liệu", MT5 Gateway **chỉ đọc**, mỗi thay đổi có test (gồm trường hợp xấu), không bịa số liệu, không mở rộng phạm vi, đổi schema = migration mới.
