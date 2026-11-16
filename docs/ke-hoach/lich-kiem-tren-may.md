# Lịch việc kiểm trên máy — GĐ1 + GĐ2 (+ GĐ3, GĐ4) (giờ Việt Nam)

> Tạo 2026-11-14. Gộp từ `GD1-ke-hoach.md` + `GD2-ke-hoach.md` (chi tiết từng mục ở đó). Xong mục nào ghi kết quả vào file kế hoạch của giai đoạn đó rồi gạch ở đây.
> Lưu ý chung: mở web bằng **địa chỉ Tailscale** (`https://…ts.net`), không dùng `localhost` (đăng nhập sẽ báo "liên kết lạ"). Lệnh `findstr` không đọc chữ có dấu → tìm bằng chữ không dấu.

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

- [ ] **~07:00 — kết thúc 6a:** `docker compose start backend` → xem `logs\lordtrade.log` và `logs\taikhoan2.log` (`Get-Content … -Tail 40 -Encoding UTF8`) có "Nạp bù sau gián đoạn: N nến M15" → trang Thị trường không hở nến đêm qua. Ngay sau đó — **COT (GĐ1, mục 17):** `docker compose exec backend python -m gold_trading.ingestion.cli cot --dry-run` → báo cáo **chốt 10/11**, số khớp trang `cftc.gov/dea/futures/deacmxsf.htm` khối GOLD. **Từ đây bắt đầu đếm ≥ 5 ngày giao dịch chạy liên tục** (Gate GĐ1) — để máy chạy, không ngủ. **DEC-21:** mất điện / mất mạng < 1 giờ mà hệ thống tự chạy lại + nạp bù đủ → vẫn tính; > 1 giờ trong giờ mở cửa hoặc phải can thiệp → ngày đó không tính (người phát triển kiểm từ dữ liệu, bạn không cần tự theo dõi). Sau mất điện: bật máy, đăng nhập Windows → Docker + Gateway tự chạy.

## Các ngày sau

- [ ] **Sáng thứ Tư 18/11, sau 08:30 (GĐ4, chỉ đọc):** `docker compose exec backend python -m gold_trading.ingestion.cli kiem-mv --hours 24` → gửi toàn bộ nội dung cho người phát triển. Mong đợi "Tái dựng: khớp 100 %"; khoảng trống đêm 16→17/11 (6a, backend tắt) là **đúng**, không cần lo.

- [ ] **Thứ Năm 19/11, 20:25–20:45 — DOL (GĐ1 mục 13–14 + GĐ2 + GĐ3):** thẻ "Lịch sự kiện kinh tế" (trang Thị trường) phải báo "Đang trong cửa sổ" cùng lúc với băng đỏ; 20:25–20:40 trang Tổng quan có băng đỏ "Cửa sổ công bố số liệu"; sau 20:30 `docker compose exec backend python -m gold_trading.ingestion.cli lich --days 14` → dòng `CLAIMS:2026-11-19` có `số: RECEIVED ICSA=…` khớp `dol.gov/ui/data.pdf`.
- [ ] **~Thứ Sáu 20/11 — đo lại dung lượng sau 7 ngày (GĐ1 mục 20):** `docker compose exec backend python -m gold_trading.ingestion.cli dung-luong` → gửi bảng. Cùng lúc (GĐ3 7c): `docker compose exec backend python -m gold_trading.ingestion.cli nguong --days 5` → gửi toàn bộ nội dung (chỉ đọc).
- [ ] **Sáng thứ Ba 24/11, sau 08:30 (Gate GĐ4, chỉ đọc):** `docker compose exec backend python -m gold_trading.ingestion.cli kiem-mv --hours 168` → gửi toàn bộ nội dung (5 ngày giao dịch chạy liên tục từ 17/11).
- [ ] **Sau khi gửi kết quả `kiem-mv` 24/11 — ING-35 (spread theo phút, KN-03):** người phát triển mới đưa code lên `develop` (người dùng chọn 15/11: không đưa vào giữa đợt đếm 5 ngày; code đang ở nhánh `claude/vigilant-hopper-f4wuqk`, commit `3a813ab`). Sau đó dựng lại (`docker compose build --no-cache backend` → `docker compose up -d`), chờ ~10 phút → `docker compose exec backend python -m gold_trading.ingestion.cli spread-phut` → gửi nội dung (mong đợi mỗi nguồn giá có số phút > 0). Hạn: trước giữa tháng 12 (giá theo giây chỉ giữ 30 ngày).
- [ ] **Sau khi đóng Gate GĐ1 + GĐ2 — KN-13 (thẻ "Nhận định thị trường": "Chất lượng dữ liệu & đồng thuận" Cao / Trung bình / Thấp thay "Độ tin cậy %"; "Nghiêng tăng / giảm" thay LONG / SHORT):** người phát triển mới đưa code lên `develop` (người dùng chọn 16/11: dọn GĐ1, GĐ2 trước; chỉ giao diện, 137 test frontend qua; code ở nhánh `claude/affectionate-einstein-8ypy59`, commit `2ed113c`). Sau đó dựng lại frontend (`docker compose build --no-cache frontend` → `docker compose up -d`) và mở trang Tổng quan xem thẻ.
- [ ] **Thứ Tư–Sáu 25–27/11 — tuần Lễ Tạ ơn (GĐ2):** băng đỏ chặn **cả ngày** thứ Tư (có thể tới thứ Sáu) cho tới khi có số DOL — đúng chính sách. **26–27/11 (GĐ1):** đối chiếu giờ mở / đóng thật của broker với bảng giờ đặc biệt (lệch → báo để chỉnh `GT_BROKER_SPECIAL_HOURS`).
- [ ] **Thứ Sáu 04/12, 20:30 — NFP (Gate GĐ1 + GĐ2):** số NFP vào đúng giờ, đúng giá trị (`cli lich`); 20:15–20:45+ có băng đỏ, sau khi nhận số thêm 15 phút; trang Pipeline: ghi lại "độ trễ gần nhất" (phải < 10 giây); rồi chạy lại `… orchestrator.replay` → ĐẠT.

## Quyết định cần bạn ở Gate (không phải thao tác máy)

- **GĐ1:** doanh số bán lẻ (Census chặn Việt Nam) — lịch chép tay / số qua FRED / bỏ hẳn; ETF GLD/IAU — xin phép bằng văn bản / bỏ hẳn; xác nhận bản sao lưu tự động có dữ liệu mới.
- **GĐ2:** chấp nhận dời sang GĐ3–GĐ4 các phần chưa làm được vì chưa có analyst / MarketView: Fusion + vô hiệu MarketView thật (ORC-02, ORC-07, 2-C06), phía dùng kết quả coi analyst lỗi là "thiếu" (2-C04), "giảm confidence" của làn nhanh (FAST-03).
- Thứ tự đóng: **GĐ1 trước, GĐ2 sau** (DEC-19) — sớm nhất ngay sau NFP 04/12.

## Việc nhỏ để sau (không chặn Gate)

- Báo lỗi đăng nhập rõ hơn khi mở bằng `localhost` (hoặc tự chuyển sang địa chỉ Tailscale).
- Lần chạy đầu sau khi dựng lại mất ~10 giây (xét lại 2 ngày) → trong lúc đó Safety chặn (đúng thiết kế); có thể làm nhanh hơn.
