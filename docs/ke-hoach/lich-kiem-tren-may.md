# Lịch việc kiểm trên máy — GĐ1 + GĐ2 (+ GĐ3, GĐ4) (giờ Việt Nam)

> Tạo 2026-11-14. Gộp từ `GD1-ke-hoach.md` + `GD2-ke-hoach.md` (chi tiết từng mục ở đó). Xong mục nào ghi kết quả vào file kế hoạch của giai đoạn đó rồi gạch ở đây.
> Lưu ý chung: mở web bằng **địa chỉ Tailscale** (`https://…ts.net`), không dùng `localhost` (đăng nhập sẽ báo "liên kết lạ"). Lệnh `findstr` không đọc chữ có dấu → tìm bằng chữ không dấu.

> **⚠️ Từ 17/11: KHÔNG dựng lại** (không chạy `docker compose build`, không `up --build`) cho tới khi Gate GĐ1 + GĐ2 đóng. `develop` đã có code mới (gộp 17/11) — dựng lại sẽ đưa code mới vào giữa đợt đếm 5 ngày. `docker compose up -d`, `restart`, `start` / `stop`, `exec` và khởi động lại máy thì **vẫn được** (chỉ dùng lại bản đã dựng 16/11).

> **Nhắc việc trên điện thoại:** [`lich-kiem-tren-may.ics`](lich-kiem-tren-may.ics) — 9 việc từ 16/11 tới NFP 04/12, mỗi việc có chuông trước + đúng giờ, ghi sẵn lệnh (người dùng chọn 16/11). Đổi lịch ở đây thì tạo lại file.

## Thứ Hai 16/11

- [ ] **~06:00–06:15 — thị trường mở cửa (GĐ2):** trang Tổng quan có thể hiện băng đỏ "Chưa đủ dữ liệu spread để đánh giá" khoảng 3 phút rồi **tự hết**. Trang Pipeline: hai làn "Đạt". Chụp màn hình nếu băng không tự hết sau 10 phút.
- [x] (16/11 xong — kết quả ở GD2/GD3-ke-hoach) **Trong ngày, trước 22:00 — dựng lại để có công cụ replay (GĐ2):** `docker compose build --no-cache backend frontend` → `docker compose up -d` → chờ 1 phút → `docker compose exec backend python -m gold_trading.orchestrator.replay` → mong đợi 4 dòng "ĐẠT" + "KẾT LUẬN: ĐẠT" (gửi toàn bộ nội dung cho người phát triển nếu có "KHÔNG ĐẠT"). Phải làm **trước 6a** để không cắt quãng đếm 5 ngày. Lần dựng này cũng đưa lên **thẻ "Lịch sự kiện kinh tế" + "Trạng thái thị trường" + "Bối cảnh vĩ mô" + "Vị thế quỹ đầu cơ (COT)"** (GĐ3) ở trang Thị trường → xem `GD3-ke-hoach.md` mục kiểm trên máy 1–4 (chỉ nhìn, không thao tác thêm). Cũng lần dựng này đưa lên **GĐ4**: trang **Tổng quan**, thẻ **"Nhận định thị trường"** → xem `GD4-ke-hoach.md` mục kiểm trên máy 1 (chỉ nhìn; đa số lúc là "Trung lập" — đúng).
- [x] (16/11 xong — kết quả ở GD2/GD3-ke-hoach) **Ngay sau khi dựng lại (trước 22:00) — nạp bù lịch sử lãi suất + COT (GĐ3):** từng lệnh một:
  1. `docker compose exec backend python -m gold_trading.ingestion.cli h15-bu --dry-run` → mong đợi dòng "KHÁC số đã có 0" → chạy lại **không có** `--dry-run`.
  2. `docker compose exec backend python -m gold_trading.ingestion.cli cot-bu --dry-run` → mong đợi "… tuần trùng, 0 tuần lệch" + "CHẠY THỬ: đọc đúng" → chạy lại **không có** `--dry-run`. Nếu có chữ **DỪNG** hoặc "thiếu cột" → **không chạy lại**, gửi toàn bộ nội dung cho người phát triển.
  Sau 1–2 phút: thẻ "Bối cảnh vĩ mô" có mũi tên ↑/↓/→ cho lợi suất; thẻ COT có "Mức đông đúc" khác "Chưa đủ lịch sử".
- [ ] ~~Sau 22:30 — COT~~ → **dời sang sáng 17/11** (16/11: lịch ghi nhầm giờ — CFTC đăng 15:30 New York thứ Hai = **03:30 giờ VN thứ Ba 17/11**, không phải 22:30; lúc 22:30 báo cáo chốt 10/11 chưa có, còn đêm nay backend tắt cho 6a).
- [x] (16/11 xong — Gateway chạy: 2 tiến trình chính lordtrade + taikhoan2; backend `Stopped`) **~23:00 — mục 6a (GĐ1, mục 8):** kiểm Gateway đang chạy (`Get-Process python`) → `docker compose stop backend` → đi ngủ (**không** tắt Gateway, không tắt máy).

## Thứ Ba 17/11

- [x] (17/11 xong: 6a **ĐẠT** — nạp bù +29 M15, DB không hở ngoài giờ nghỉ; đếm 5 ngày từ 08:02; COT chốt 10/11 **khớp cftc.gov**) **~07:00 — kết thúc 6a:** `docker compose start backend` → xem `mt5_gateway\logs\lordtrade.log` và `mt5_gateway\logs\taikhoan2.log` (trên máy: `C:\gold-trading\code\gold_trading-develop\mt5_gateway\logs`) (`Get-Content … -Tail 40 -Encoding UTF8`) có "Nạp bù sau gián đoạn: N nến M15" → trang Thị trường không hở nến đêm qua. Ngay sau đó — **COT (GĐ1, mục 17):** `docker compose exec backend python -m gold_trading.ingestion.cli cot --dry-run` → báo cáo **chốt 10/11**, số khớp trang `cftc.gov/dea/futures/deacmxsf.htm` khối GOLD. **Từ đây bắt đầu đếm ≥ 5 ngày giao dịch chạy liên tục** (Gate GĐ1) — để máy chạy, không ngủ. **DEC-21:** mất điện / mất mạng < 1 giờ mà hệ thống tự chạy lại + nạp bù đủ → vẫn tính; > 1 giờ trong giờ mở cửa hoặc phải can thiệp → ngày đó không tính (người phát triển kiểm từ dữ liệu, bạn không cần tự theo dõi). Sau mất điện: bật máy, đăng nhập Windows → Docker + Gateway tự chạy.

## Các ngày sau

- [x] (18/11 xong — khớp 100 %, phủ 98,9 %; kết quả ở GD4-ke-hoach mục 3) **Sáng thứ Tư 18/11, sau 08:30 (GĐ4, chỉ đọc):** `docker compose exec backend python -m gold_trading.ingestion.cli kiem-mv --hours 24` → gửi toàn bộ nội dung cho người phát triển. Mong đợi "Tái dựng: khớp 100 %"; khoảng trống đêm 16→17/11 (6a, backend tắt) là **đúng**, không cần lo.

- [x] (19/11 xong — băng đỏ + thẻ lịch cùng tới 20:40; ICSA 203000 + 3 số sửa khớp `data.pdf`; nhật ký GĐ1) **Thứ Năm 19/11, 20:25–20:45 — DOL (GĐ1 mục 13–14 + GĐ2 + GĐ3):** thẻ "Lịch sự kiện kinh tế" (trang Thị trường) phải báo "Đang trong cửa sổ" cùng lúc với băng đỏ; 20:25–20:40 trang Tổng quan có băng đỏ "Cửa sổ công bố số liệu"; sau 20:30 `docker compose exec backend python -m gold_trading.ingestion.cli lich --days 14` → dòng `CLAIMS:2026-11-19` có `số: RECEIVED ICSA=…` khớp `dol.gov/ui/data.pdf`.
- [x] (21/11 xong: `dung-luong` 244 MB, ~1,8 GB/năm, giữ nguyên chính sách; `nguong` 0 lần vượt R3/R5 → giữ ngưỡng — GD3-ke-hoach mục 5) **Sáng thứ Bảy 21/11, 08:00–10:00 (người dùng dời từ thứ Sáu 20/11, chọn 19–20/11; làm trước khi cập nhật MT5) — đo lại dung lượng sau 7 ngày (GĐ1 mục 20):** `docker compose exec backend python -m gold_trading.ingestion.cli dung-luong` → gửi bảng. Cùng lúc (GĐ3 7c): `docker compose exec backend python -m gold_trading.ingestion.cli nguong --days 5` → gửi toàn bộ nội dung (chỉ đọc).
- [ ] **Sáng thứ Bảy 21/11 (thị trường đóng) — cập nhật MT5 (LiveUpdate báo 18/11, người dùng bấm "Later"):** làm **từng cửa sổ MT5 một**: bấm "Restart" ở hộp LiveUpdate (hoặc tắt MT5 bằng File → Exit rồi mở lại từ biểu tượng cũ — bản cập nhật tự cài lúc mở) → chờ MT5 mở lại, góc dưới bên phải có cột tín hiệu, **không** báo "No connection" / "Invalid account" (nếu bắt đăng nhập: gõ mật khẩu ngay trong MT5, không gửi cho ai) → làm cửa sổ còn lại. Sau đó: `Get-Process python` (phải còn Gateway) và xem 20 dòng cuối log Gateway mỗi tài khoản (`Get-Content C:\gold-trading\code\gold_trading-develop\mt5_gateway\logs\lordtrade.log -Tail 20 -Encoding UTF8`, tương tự `taikhoan2.log`) có "MT5 đã kết nối lại máy chủ broker" → gửi cho người phát triển. Thứ Bảy không nến mới là đúng (thị trường đóng). **Không** tắt Docker / backend, **không** dựng lại.

- [ ] **Sáng thứ Ba 24/11, sau 08:30 (Gate GĐ4, chỉ đọc):** `docker compose exec backend python -m gold_trading.ingestion.cli kiem-mv --hours 168` → gửi toàn bộ nội dung (5 ngày giao dịch chạy liên tục từ 17/11).
- [ ] **Sau khi đóng Gate GĐ1 + GĐ2 — MỘT lần dựng lại cho tất cả code mới** (người dùng chọn 17/11: gộp hết vào `develop` ngay — nhánh chờ KN-03/05/13/14/15/20/21/26 + GĐ5 — nhưng **chưa dựng lại**; thay cho lần dựng 24/11 cũ): `docker compose build --no-cache backend frontend` → `docker compose up -d`. Sau đó: (1) **ING-35** chờ ~10 phút → `docker compose exec backend python -m gold_trading.ingestion.cli spread-phut` → gửi nội dung (mong đợi mỗi nguồn giá có số phút > 0); hạn: trước giữa tháng 12 (giá theo giây chỉ giữ 30 ngày — Gate trễ quá thì báo người phát triển); (2) **KN-13** mở trang Tổng quan xem thẻ "Nhận định thị trường" ("Chất lượng dữ liệu & đồng thuận" Cao / Trung bình / Thấp; "Nghiêng tăng / giảm"); (3) **Lịch bán lẻ Census chép tay**: trang Nguồn dữ liệu có dòng "Lịch doanh số bán lẻ (Census, chép tay)" ở trạng thái Đạt, và `docker compose exec backend python -m gold_trading.ingestion.cli lich --days 60` có dòng `RETAIL:2026-11` (16/12, 08:30 New York); (4) **GĐ5** làm bước B–E ở [`GD5-ke-hoach.md`](GD5-ke-hoach.md) (có thể làm ngày khác).
- [ ] **Thứ Tư–Sáu 25–27/11 — tuần Lễ Tạ ơn (GĐ2):** băng đỏ chặn **cả ngày** thứ Tư (có thể tới thứ Sáu) cho tới khi có số DOL — đúng chính sách. **26–27/11 (GĐ1):** đối chiếu giờ mở / đóng thật của broker với bảng giờ đặc biệt (lệch → báo để chỉnh `GT_BROKER_SPECIAL_HOURS`).
- [ ] **Thứ Sáu 04/12, 20:30 — NFP (Gate GĐ1 + GĐ2):** số NFP vào đúng giờ, đúng giá trị (`cli lich`); 20:15–20:45+ có băng đỏ, sau khi nhận số thêm 15 phút; trang Pipeline: ghi lại "độ trễ gần nhất" (phải < 10 giây); rồi chạy lại `… orchestrator.replay` → ĐẠT.

- [ ] **Sau lần dựng lại ở trên, ngày bạn chọn (không tối thứ Sáu, không trong khung tin) — Gate GĐ5 (kế hoạch giao dịch, chỉ PAPER):** GĐ5 đã ở `develop` (17/11); làm bước A–E ở [`GD5-ke-hoach.md`](GD5-ke-hoach.md) mục "Kiểm trên máy người dùng (Gate GĐ5)": mở trang Rủi ro, nhập hồ sơ + phí, bắt đầu sổ paper, chạy `cli kha-thi`, sau 1–2 ngày xác nhận MT5 **không có lệnh mới nào**.

## Quyết định cần bạn ở Gate (không phải thao tác máy)

- **GĐ1:** doanh số bán lẻ (Census chặn Việt Nam) — lịch chép tay / số qua FRED / bỏ hẳn; ETF GLD/IAU — xin phép bằng văn bản / bỏ hẳn; xác nhận bản sao lưu tự động có dữ liệu mới.
- **GĐ2:** chấp nhận dời sang GĐ3–GĐ4 các phần chưa làm được vì chưa có analyst / MarketView: Fusion + vô hiệu MarketView thật (ORC-02, ORC-07, 2-C06), phía dùng kết quả coi analyst lỗi là "thiếu" (2-C04), "giảm confidence" của làn nhanh (FAST-03).
- Thứ tự đóng: **GĐ1 trước, GĐ2 sau** (DEC-19) — sớm nhất ngay sau NFP 04/12.

## Việc nhỏ để sau (không chặn Gate)

- Báo lỗi đăng nhập rõ hơn khi mở bằng `localhost` (hoặc tự chuyển sang địa chỉ Tailscale).
- Lần chạy đầu sau khi dựng lại mất ~10 giây (xét lại 2 ngày) → trong lúc đó Safety chặn (đúng thiết kế); có thể làm nhanh hơn.
