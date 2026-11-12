# Thiết kế — MT5 Gateway bản CHỈ ĐỌC (v1)

> Mục tiêu: đưa nến XAUUSD M15 **thật** từ MT5 (tài khoản demo) vào hệ thống. **Không có bất kỳ chức năng đặt, sửa hay hủy lệnh nào.**

## 1. Ranh giới an toàn

- Gateway chỉ gọi các hàm **đọc** của thư viện `MetaTrader5`: `initialize`, `shutdown`, `last_error`, `terminal_info`, `account_info`, `symbol_info`, `symbol_select`, `symbol_info_tick`, `copy_rates_from_pos`.
- Có test quét mã nguồn: nếu xuất hiện `order_send`, `order_check`, `positions_`, `orders_` thì **test thất bại**.
- Gateway hiển thị loại tài khoản (DEMO / CONTEST / REAL). Tài khoản REAL vẫn chỉ đọc, nhưng có cảnh báo rõ.

## 2. Giờ của MT5: điểm dễ sai nhất

- `copy_rates_*` và `symbol_info_tick` trả `time` là số giây, nhưng đó là **giờ server của broker viết như thể UTC** (không phải UTC thật).
- Cách quy đổi: `server_local = datetime.fromtimestamp(t, UTC).replace(tzinfo=None)`, sau đó gắn múi giờ server dạng **IANA** (ví dụ `Europe/Athens` cho broker GMT+2/GMT+3), rồi đổi sang UTC. Giờ mơ hồ hoặc không tồn tại do đổi DST thì **bỏ nến đó và báo lỗi**, không đoán.
- **Không chấp nhận độ lệch giờ cố định** (+2/+3) cho dữ liệu lịch sử, vì broker đổi giờ theo mùa. Bắt buộc dùng tên múi giờ IANA.
- Kiểm tra chéo hai lớp:
  1. **Độ lệch hiện tại:** khi thị trường mở, so `tick.time` với đồng hồ thật. Độ lệch phải khớp với múi giờ đã khai báo (sai số tối đa 5 phút). Không khớp thì **từ chối chạy**.
  2. **R1 trên lịch sử:** gửi ~5.000 nến lịch sử (khoảng 2 tháng) cho backend kiểm tra ở chế độ chạy thử (dry-run). Hơn 1% nến rơi vào giờ đóng cửa thì **từ chối chạy** và gợi ý độ lệch.

## 3. Chỉ lấy nến đã đóng

- `copy_rates_from_pos(symbol, M15, start_pos=1, count)`: vị trí 0 là nến **đang chạy**, nên luôn bắt đầu từ vị trí 1.
- Backend kiểm tra thêm một lần: nến có `close_time` lớn hơn giờ nhận thì cách ly với lý do `BAR_NOT_CLOSED`.

### 3b. Nến cuối phiên trước cuối tuần / ngày lễ / giờ nghỉ (1A-C21, 2026-11-07)

**Vấn đề:** MT5 chỉ đẩy nến sang vị trí 1 khi có tick của nến kế tiếp. Nến cuối trước khi thị trường đóng (tối thứ Sáu, ngày lễ, giờ nghỉ hằng ngày) nằm ở vị trí 0 tới khi thị trường mở lại → trước đây tới thứ Hai mới gửi (trễ ~2 ngày; D1/H4/H1/M15 thứ Sáu đều bị giữ).

**Cách làm:**

- Gateway đọc vị trí 0..N trong **một** lần gọi (`Mt5Reader.bars_with_tail`), gửi nến đã đóng trong `bars` như cũ và nến vị trí 0 **riêng** trong `tail_bar` — chỉ khi terminal đang kết nối (`terminal_info().connected`) và chỉ với lô realtime. Nạp bù không bao giờ gửi `tail_bar` (backend trả 422 nếu có).
- **Backend quyết định** (đồng hồ backend + lịch đầy đủ `MarketCalendar`), hàm `ingestion/candles.tail_status`. Chỉ nhận khi CẢ HAI:
  1. `close_time + 2 phút ≤ giờ backend` (`TAIL_GRACE`, để terminal nhận nốt tick cuối; H4/D1 tính `close_time` theo giờ server, ngày đổi giờ dài/ngắn đúng thực tế);
  2. lịch báo **đóng cửa suốt** từ `close_time` tới giờ hiện tại (quét từng phút; quá 7 ngày → không xác minh được → giữ).
- Nhận (`INCLUDED`) thì nến đi qua đúng các bước kiểm tra như nến thường (OHLC, căn khung, khử trùng); `available_at` = lúc nhận (không phải `close_time`). Không nhận thì bỏ qua, **không lưu, không cách ly** (`HELD_NOT_CLOSED`, `HELD_MARKET_OPEN`, `HELD_NOT_LATEST`); trường `tail` trong kết quả cho biết số phận.
- Thứ Hai, MT5 đẩy nến đó sang vị trí 1, Gateway gửi như nến thường → trùng (bỏ qua) hoặc, nếu terminal đã nhận thêm tick trễ, thành **revision** có cờ `REVISED` (không ghi đè).
- Gateway nhớ nến vị trí 0 nào đã được nhận để không gửi lại.

**Lý do chọn điều kiện 2 ("đóng suốt"):** nếu lịch còn mở ở phút nào đó sau khi nến hết giờ mà vẫn không có nến mới, có thể terminal mất kết nối hoặc chậm → nến có thể thiếu tick → giữ lại (chậm như cũ, an toàn). Lịch broker khai sai (thiếu `GT_BROKER_SESSIONS`, giờ đóng khai muộn hơn thật) chỉ làm nến bị giữ tới thứ Hai như trước, **không bao giờ nhận sớm**. Khai giờ đóng **sớm hơn** thật mới có rủi ro (nến lúc broker còn mở bị coi là cuối phiên) — R1 (lúc nạp bù: > 1% nến rơi vào giờ lịch báo đóng → từ chối) giúp phát hiện lịch tuần khai sai.

### 3a. Khung H1, H4, D1 (ING-14, 2026-11-07)

- Đọc thẳng từ MT5 bằng `copy_rates_from_pos(symbol, TIMEFRAME_H1/H4/D1, 1, count)`, **không** ghép từ M15. Lịch sử tối đa: H1 2.000, H4 1.000, D1 500 nến (xin nhiều hơn làm MT5 đứng lâu để tải). Khung chọn bằng `GT_TIMEFRAMES` (mặc định `M15,H1,H4,D1`; M15 luôn có vì R1 kiểm múi giờ trên M15).
- MT5 cắt H4/D1 theo **đồng hồ server**: D1 mở 00:00 giờ server, H4 lúc 00/04/…/20 giờ server. Ví dụ Europe/Athens mùa đông, D1 mở 22:00 UTC hôm trước. Gateway chỉ đổi sang UTC, không cắt lại.
- Lô H4/D1 bắt buộc kèm `server_tz` (tên IANA). Backend dùng nó để (1) kiểm `open_time` đúng ranh giới giờ server — sai thì cách ly `MISALIGNED_TIME`; (2) tính `close_time` thật = ranh giới kế tiếp theo giờ server (ngày đổi giờ: 23/25 h hoặc 3/5 h). Giờ ranh giới mơ hồ → lấy lần muộn hơn; không tồn tại → lúc đồng hồ vượt qua. Lý do: không bao giờ coi một nến là đã đóng sớm hơn thực tế (point-in-time).
- Nếu backend có `GT_BROKER_SERVER_TZ` mà khác `server_tz` của Gateway → từ chối lô H4/D1 (422): hai cấu hình mâu thuẫn thì không đoán.
- R1 áp cho M15 và H1; H4/D1 vắt qua giờ nghỉ nên không áp.
- `check` bước 10 chạy thử từng khung; khung nào lỗi chỉ **CẢNH BÁO** và không được gửi, M15 vẫn chạy.
- Khi chạy: khung lớn gửi 3 nến gần nhất khi có nến mới đóng, hoặc 60 giây/lần để bắt bản sửa. Lỗi riêng một khung không làm ngừng M15.

## 4. Đồng bộ

| Giai đoạn | Làm gì | `backfill` |
| --- | --- | --- |
| Khởi động | Gửi 5.000 nến gần nhất theo lô 1.000 | `true`: `available_at = close_time`, cờ `BACKFILL` |
| Chạy liên tục | Cứ 5 giây lấy 20 nến đã đóng gần nhất và gửi | `false`: `available_at` = lúc backend nhận |
| Mất kết nối rồi kết nối lại | Vòng lặp tự gửi lại; backend bỏ qua nến trùng | `false`: nến bị lỡ được ghi nhận đúng lúc nhận (trung thực, không "biết trước") |

- Thời điểm nhận dùng **đồng hồ của backend**, không dùng đồng hồ máy chạy Gateway.
- Lỗi mạng hoặc backend: thử lại với thời gian chờ tăng dần (1 → 30 giây). Không bỏ dữ liệu: lần gửi sau lấy lại 20 nến gần nhất.

## 5. Backend nhận dữ liệu

- `POST /api/ingest/mt5/candles` và `POST /api/ingest/mt5/heartbeat`, bắt buộc header `Authorization: Bearer <GT_INGEST_TOKEN>`.
  - Backend không đặt token thì endpoint **tắt** (503).
  - Token phải dài ít nhất 24 ký tự; so sánh bằng `hmac.compare_digest`.
- Chỉ nhận symbol khớp symbol của hệ thống (`XAUUSD`) và khung `M15`, `H1`, `H4`, `D1` (H4/D1 kèm `server_tz`, mục 3a); tối đa 2.000 nến mỗi lần.
- `dry_run=true`: kiểm tra (R1 + kiểm tra từng nến) nhưng **không lưu**.
- `GET /api/gateway/status`: nhịp tim gần nhất, loại tài khoản, server, thông số symbol (contract size, lot tối thiểu, bước lot, digits). Quá 30 giây không có nhịp tim thì coi là mất kết nối.

### 5a. Danh tính MT5 + số liệu tài khoản trong nhịp tim (MT-12 + GW-09, 2026-11-07, Gateway 0.3.0)

- Mỗi nhịp tim (10 giây) Gateway gọi lại `account_info()`, `terminal_info()`, `symbol_info()` (đều đã có trong `READ_ONLY_FUNCTIONS`, không thêm hàm MT5 mới). **Không** dùng giá trị đọc lúc `check`: người dùng có thể đổi tài khoản trong terminal khi Gateway đang chạy, MT-14 cần thấy ngay.
- `identity` = `{login, server, company, account_type, terminal_name, terminal_path}`. Danh tính MT5 = `(login, server)`. Chưa đăng nhập (`account_info()` None/lỗi, `login ≤ 0`, server rỗng) → `identity: null`, `account: null`, trường cũ `account_type = UNKNOWN`, `server = null`.
- `account` = `{currency, balance, equity, margin, margin_free, margin_level, leverage, trade_allowed}`. `margin_level` = `null` khi `margin = 0` (MT5 trả 0 nhưng thực ra không xác định).
- `symbol` thêm `stops_level`, `freeze_level` (point), `swap_mode`, `swap_long`, `swap_short`, `swap_rollover3days`. Thiếu thông số cốt lõi (digits, point > 0, contract/volume) → cả `symbol: null`, không gửi nửa vời. **Commission:** thư viện MT5 không có trong `symbol_info` → không gửi (lấy từ lịch sử deal ở GĐ9 nếu cần).
- Số NaN/Inf hoặc sai kiểu → `null` cho đúng trường đó (Gateway); backend từ chối NaN/Inf, số âm vô lý (đòn bẩy ≤ 0, margin < 0, stops level < 0, point ≤ 0), login ≤ 0 hoặc ≥ 2^63, chuỗi > 256 ký tự (422).
- Backend kiểm `identity.server == server` và `identity.account_type == account_type` (hai trường cũ giữ cho tương thích, cùng một lần đọc). Lệch, hoặc có `account` mà không có `identity` → 422, không chọn bừa một bên.
- Gateway cũ (không có trường mới) vẫn được nhận: trường mới = `null` (không phải 0).
- Hiển thị: trang **Tài khoản** của USER (thẻ "MT5 đang kết nối"); tài khoản REAL có cảnh báo. ADMIN và USER khác không xem được (`Guard.check`); danh sách Quản trị chỉ có trạng thái kết nối.
- **Liên kết (MT-13, 2026-11-07):** danh tính trong nhịp tim tạo liên kết chờ xác nhận ở bảng `mt5_links` (xem `00-xac-thuc-phan-quyen.md` mục 14.5). Chuyển MISMATCH/chặn ghi khi đổi tài khoản: mục 5b (MT-14). Hiện tại terminal đăng xuất vẫn hiện CONNECTED nếu Gateway còn đọc được nến (chỉ `identity: null`) — MT-14 xử lý.

### 5b. Danh tính MT5 trong lô nến + chờ liên kết (MT-14, 2026-11-11, Gateway 0.4.0)

- Mỗi lô nến (cả nạp bù, realtime, chạy thử) gửi `mt5_login`, `mt5_server`, `mt5_account_type`. Gateway đọc danh tính **ngay trước và ngay sau** khi lấy nến (`Syncer._read`): chưa đăng nhập, hoặc hai lần đọc khác nhau (vừa đổi tài khoản giữa chừng) → **bỏ lô**, không gửi nến không rõ thuộc MT5 nào.
- Backend chỉ **ghi** khi danh tính khớp liên kết `ACTIVE` của tài khoản (chi tiết `00-xac-thuc-phan-quyen.md` mục 14.6). Từ chối vì liên kết → `409` với `detail` bắt đầu bằng `MT5_LINK_REQUIRED` / `MT5_LINK_MISMATCH`. `dry_run` không chặn, trả thêm `link_status`; `check` hiện bước "Liên kết MT5" dạng **cảnh báo** (không chặn `run`, vì `run` cần gửi nhịp tim thì web mới hiện MT5 để xác nhận).
- `run_forever`: nhịp tim gửi đúng lịch **trước** việc gửi nến, kể cả khi nến bị từ chối / backend hay MT5 lỗi (trước đây lỗi gửi nến làm bỏ nhịp tim). Gặp `409 MT5_LINK_*` → không thoát, không tăng backoff, ghi log một lần, thử lại sau 30 s; khi thông lại thì **nạp bù lại cả lịch sử** (backend khử trùng) để không hụt nến của thời gian bị chặn. Nạp bù cũng chạy trong vòng này (CLI không nạp bù riêng nữa).
- Gateway < 0.4.0 gửi nến không có danh tính → bị từ chối (`MT5_LINK_REQUIRED`, có ghi "cập nhật lên ≥ 0.4.0"). Phải cập nhật Gateway cùng lúc với backend.

### 5c. Nguồn giá theo broker (MT-05 phần lưu trữ, 2026-11-11, Gateway 0.5.0, migration 0009)

- **Nguồn giá (feed)** = `(server broker, symbol broker)`; `feed_id = "pf_" + sha256(lower(server) + "\0" + broker_symbol)[:24]` (`market/feeds.py`). Server không phân biệt hoa/thường (như MT-13); symbol giữ nguyên chữ; tên có ký tự điều khiển / khoảng trắng đầu-cuối bị từ chối (soát lại tìm được: NUL làm hai cặp khác nhau ra cùng mã). Bảng `price_feeds` (chỉ thêm) lưu server + symbol để hiển thị.
- Kho nến, cách ly, kết quả analyst có cột `feed_id`; khóa chính `candles` thêm `feed_id`. **Mọi** đọc/ghi đi theo đúng một feed (tham số `feed=` ở `CandleStore`, `CandleIngestor.ingest`, `AnalystOutputStore`); khử trùng, revision, cờ GAP chỉ so với nến cùng feed → hai broker không bao giờ trộn hay "sửa" nến của nhau. `""` = nguồn không gắn broker (SAMPLE / CSV).
- Gateway 0.5.0 gửi thêm `broker_symbol` (= `GT_BROKER_SYMBOL`). Backend: lô ghi thật phải có (thiếu → `MT5_LINK_REQUIRED`, ghi "cập nhật ≥ 0.5.0"; chỉ nhận ký tự ASCII in được). Symbol **khóa vào liên kết** ở lô đầu tiên được ghi (`mt5_links.broker_symbol`, audit `price_feed.bind`); lô sau khác symbol → `409 MT5_LINK_SYMBOL` (nguồn khác — ING-15), phải gỡ + liên kết lại. Feed tính từ server **của liên kết** (không phải chuỗi trong lô).
- Bỏ điều kiện "chỉ tài khoản `price_feed` được ghi": mọi tài khoản có liên kết ACTIVE ghi vào nguồn của mình; hai tài khoản cùng server + symbol ghi chung một nguồn (khử trùng).
- **Dữ liệu cũ:** nến / cách ly / kết quả analyst MT5 trước 0009 không biết của broker nào → `feed_id = 'legacy-unknown-broker'`, giữ để tra cứu, **không** tài khoản nào đọc. Gateway nạp bù lại lịch sử vào đúng nguồn sau khi liên kết. Hạ cấp 0009 bị từ chối nếu đã có nhiều nguồn MT5.
- **Đọc (MT-05 phần đọc, 2026-11-11):** giá + phân tích theo nguồn của **chính tài khoản**: `GET /api/accounts/{id}/market/summary|candles|quality` và `/api/accounts/{id}/analysts/technical/latest` (qua `Guard.check`: chỉ chủ tài khoản ACTIVE; ADMIN/người khác 404). Nguồn = liên kết đang giữ đã khóa symbol (`account_feed`); chưa có → không có dữ liệu (không mượn nguồn tài khoản khác). Liên kết MISMATCH vẫn xem được nến cũ của đúng nguồn (chỉ chặn ghi). **Không còn "giá chung" MT5**: `/api/market/*`, `/api/analysts/technical/latest` với nguồn MT5 luôn rỗng (vẫn dùng cho SAMPLE/CSV); cờ `price_feed` của tài khoản không còn ảnh hưởng đọc/ghi. Giao diện (header, trang Thị trường) gọi endpoint theo tài khoản đang chọn; ADMIN không xem giá broker.
- **Analyst theo từng nguồn:** `TechnicalRunner(feeds=...)` chạy cho mỗi nguồn đang được ít nhất một tài khoản dùng; lỗi ở một nguồn không chặn nguồn khác. Kết quả duy nhất theo `(feed_id, output_id)` (migration **0010**): hai broker có nến giống hệt nhau (cùng nhà cung cấp thanh khoản) vẫn mỗi nguồn một kết quả — trước đó nguồn thứ hai bị coi là trùng và không bao giờ có kết quả (tìm được khi soát).
- **Giới hạn:** lịch phiên broker (`GT_BROKER_SERVER_TZ`, `GT_BROKER_SESSIONS`, `GT_BROKER_SPECIAL_HOURS`) vẫn là **một** cấu hình cho cả hệ thống: các broker khác giờ phiên / múi giờ server sẽ bị kiểm R1, cờ GAP, độ mới theo cấu hình đó. Cần lịch theo từng nguồn trước khi dùng nhiều broker khác giờ thật (ghi nhận cho MT-15 / sau GĐ1).

### 5d. Nhiều terminal MT5 trên một máy (MT-15, 2026-11-12, Gateway 0.6.0)

- Thư viện `MetaTrader5` nối **một** terminal mỗi tiến trình Python (hàm cấp module) → "một Gateway quản lý nhiều terminal" = tiến trình cha `run-all` (`multi.py`) chạy **mỗi terminal một tiến trình con** `mt5-gateway run --env-file terminals/<tên>.env --name <tên>`. Cha không đọc MT5, không gọi backend; chỉ kiểm cấu hình, khởi động (giãn 3 s), chạy lại con khi con dừng (30 s, gấp đôi tới 5 phút; chạy ≥ 10 phút rồi mới dừng thì đặt lại 30 s), Ctrl+C dừng hết (terminate, quá 10 s thì kill).
- **Cấu hình:** `terminals/<tên>.env`, mỗi file một terminal, cùng khóa như `gateway.env` (`.gitignore` chặn commit). Tên file `[A-Za-z0-9_-]{1,32}`; tối đa 20 terminal. Bắt buộc `GT_MT5_PATH` (file phải tồn tại) và token ≥ 24 ký tự. **Một lỗi cấu hình → không chạy terminal nào** (mặc định an toàn): chung token, cùng terminal (so thư mục đã chuẩn hóa kiểu Windows: không phân biệt hoa/thường, `/` = `\`, bỏ `terminal64.exe`, bỏ dấu nháy), trùng `GT_GATEWAY_ID` (không phân biệt hoa/thường). Thông báo lỗi chỉ nêu tên file, **không bao giờ in token**. `gateway_id` mặc định `<tên máy>-<tên terminal>`.
- **Biến môi trường:** ở chế độ nhiều terminal, `config.load(use_environ=False)` và tiến trình con chạy với môi trường đã **bỏ mọi biến `GT_*`** — một `GT_INGEST_TOKEN` đặt chung trong Windows sẽ biến mọi terminal thành chung token. Chế độ một terminal giữ như cũ (biến môi trường đè file).
- **Đúng terminal** (cả chế độ một terminal khi đã đặt `GT_MT5_PATH`): sau `initialize(path)` và **trước mỗi lần đọc nến** (`Syncer._read`), `terminal_info().path` phải trùng thư mục của `GT_MT5_PATH`; sai hoặc không đọc được → `TerminalMismatch` (`TERMINAL_MISMATCH`): `check` LỖI, `connect` buông terminal đó (`shutdown`), vòng chạy không gửi gì và nối lại; không tắt khung H1/H4/D1 vì lỗi này. Không đặt `GT_MT5_PATH` → không kiểm (máy một MT5, như cũ).
- **Lớp phòng thủ phía backend (đã có, MT-13/14):** dù cấu hình sai lọt qua (ví dụ hai cửa sổ `run` riêng dùng chung token), nến chỉ ghi khi danh tính MT5 khớp liên kết ACTIVE của tài khoản của token → MT5 lạ thành MISMATCH, không ghi.
- **Không đổi backend / schema / contract.**
- **Giới hạn:** lịch phiên broker vẫn một cấu hình chung (mục 5c) — nhiều broker khác giờ server cần lịch theo nguồn; terminal có `check` chưa đạt thì không gửi nhịp tim, web của người dùng đó chỉ thấy "chưa kết nối" (chi tiết lỗi ở cửa sổ Gateway); chưa chạy như dịch vụ Windows (GW-06, bước 6); chưa chạy với nhiều MT5 thật.

### 5e. Giá sống bid/ask/spread theo giây (ING-08, 2026-11-12, migration 0011)

- **Vì sao gom theo giây:** XAUUSD có thể nhiều tick mỗi giây; lưu từng tick tốn chỗ mà không cần cho giao dịch khung M15 trở lên. Mỗi `(nguồn giá, giây)` một dòng: giá **cuối** giây (bid, ask, spread), bid **thấp nhất**, ask **cao nhất**, spread **lớn nhất**, số tick. Gateway chỉ gửi giây **đã trọn** (giây đang chạy chưa gửi). Giá trị luôn là giá thật broker báo, không làm tròn, không nội suy giây thiếu (giây không có tick thì không có dòng).
- **`POST /api/ingest/mt5/quotes`** (≤ 600 giây/lô): `symbol`, `gateway_id`, danh tính MT5 + `broker_symbol` (bắt buộc), `point`, `seconds[]`, `gateway_dropped` (Gateway tự đếm tick bỏ). Kiểm danh tính + khóa symbol **y như lô nến** (`check_candle_identity`, `lock_feed`): chưa liên kết / MT5 khác / symbol khác → 409. Trả `received/accepted/duplicates/conflicts/dropped/wide_spread/calendar_closed/calendar_mismatch`.
- **Kiểm lại từng giây** (`market/quotes.py::check_quote`, 1A-C13) — bỏ + đếm theo lý do, không sửa giá trị: `NOT_WHOLE_SECOND`, `FUTURE` (> giờ backend + 2 s), `TOO_OLD` (quá hạn giữ), `NON_POSITIVE`, `CROSSED` (bid > ask), `INCONSISTENT` (bid thấp nhất > bid, ask cao nhất < ask, spread lớn nhất < spread cuối − 1 point, tick < 1), `DUPLICATE_IN_BATCH` (giữ bản đầu). Giây đã lưu → giữ bản đầu (`duplicates`; khác giá trị → `conflicts`, ví dụ hai tài khoản cùng broker). Giây tới muộn vẫn lưu đúng giây của nó, `available_at` = lúc nhận (point-in-time, không viết lại quá khứ). DB thêm ràng buộc `bid > 0 AND ask >= bid ...`.
- **Cờ** (ghi nhận, chưa nối Safety): `WIDE_SPREAD` khi spread lớn nhất trong giây > `WIDE_SPREAD_MULTIPLE` (3, cùng ngưỡng R5 của nến) × trung vị spread cuối giây của **1 giờ trước** cùng nguồn (bỏ các giây lịch đóng cửa); < 60 mẫu → `SPREAD_UNRATED` (không kết luận là bình thường). `CALENDAR_CLOSED` khi lịch (`MarketCalendar.is_open`) nói đóng cửa — vẫn lưu, không coi là thị trường mở; ≥ 30 giây như vậy trong 10 phút gần nhất → `calendar_mismatch` + log `CALENDAR_MISMATCH`. Ngưỡng chưa hiệu chỉnh trên dữ liệu thật.
- **Giữ dữ liệu:** `GT_QUOTE_RETENTION_DAYS` (mặc định 30, 1–365). Việc xóa chạy kèm lúc nhận, tối đa mỗi giờ một lần. Đây là **ngoại lệ append-only duy nhất**: trigger `quote_seconds_no_update` chỉ chặn UPDATE; DELETE chỉ do `purge_before`. Ước tính ~1 dòng/giây mở cửa ≈ 2 triệu dòng/nguồn/tháng.
- **Gateway (GW-08, 0.7.0, `quotes.py`):** `copy_ticks_from(symbol, mốc, 20000, COPY_TICKS_INFO)` với mốc = giây server đầu tiên chưa gửi (cùng hệ "giờ server viết như UTC" với thời gian MT5 trả về). Gom theo giây; chốt giây khi đã có tick của giây sau hoặc giờ server đã qua ≥ 2 giây; đọc đủ 20.000 tick thì chỉ chốt tới trước giây của tick cuối. Bỏ + đếm tick lỗi (`NON_POSITIVE`, `CROSSED`, `OUT_OF_ORDER`, `DUPLICATE` = cùng ms + cùng giá; cùng ms khác giá vẫn giữ), giây mơ hồ DST → `AMBIGUOUS_TIME`. Bắt đầu 60 s trước; mốc cũ hơn 10 phút → nhảy tới (không nạp bù giá sống dài). Chỉ tiến mốc khi backend nhận; lỗi → gửi lại đúng các giây đó. Mỗi lô kẹp giữa hai lần đọc danh tính (MT-14). **Tự kiểm mốc** (chưa kiểm được với thư viện thật): tick trả về sớm hơn mốc > 60 s, hoặc rỗng trong khi `symbol_info_tick` có tick sau mốc > 10 s → `TickRequestMismatch` → tắt giá sống (nến vẫn chạy). Backend 404 → tắt; 409 liên kết → chờ như nến. `check` bước "Giá sống (bid/ask)" chỉ CẢNH BÁO.
- **1A-C08 (`TzWatch`):** mỗi vòng đọc `symbol_info_tick().time_msc`; chỉ xét khi khác lần trước (tick vừa tới, nên giờ server của nó − giờ UTC máy ≈ độ lệch thật; tick đứng yên sau giờ đóng cửa có thể lệch đúng 1 giờ → bỏ qua). Lệch khác `GT_SERVER_TZ` → **tạm dừng** gửi nến + giá ngay (`SERVER_TZ_SUSPECT`); 3 lần liên tiếp trải ≥ 60 s → chặn (`SERVER_TZ_CHANGED`), chỉ gỡ khi khớp 3 lần liên tiếp; khớp lại thì nạp bù lại nến (backend khử trùng). Nhịp tim gửi `server_offset_hours_now` đang thấy. So "khác" chứ không "lớn hơn": broker lùi giờ thì tick mới có giờ server nhỏ hơn.
- **Chưa có:** màn hình + đọc theo tài khoản (5c).

## 6. Lệnh cho người dùng

- `mt5-gateway check`: chẩn đoán từng bước, mỗi bước báo **ĐẠT / LỖI** kèm cách sửa. Không ghi dữ liệu.
- `mt5-gateway run`: chạy `check` trước; tất cả đạt mới bắt đầu đồng bộ.
- `mt5-gateway check-all` / `run-all` (MT-15): như trên cho mọi terminal trong `terminals/` (mục 5d).

## 7. Kết quả kiểm chứng (2026-11-05, với MT5 giả lập)

- 26 test Gateway: quy đổi giờ mùa đông/mùa hè, giờ mơ hồ do DST, chỉ lấy nến đã đóng, chặn hàm giao dịch (wrapper + quét mã nguồn), từng bước `check`, đồng bộ, backoff.
- Tích hợp thật qua HTTP và nginx trên Docker + PostgreSQL: `check` đạt 9/9; nạp bù 4.596 nến; nhịp tim CONNECTED/DEMO; Technical analyst HEALTHY trên nguồn MT5.
- Sai múi giờ khi không có tick để đối chiếu: bị chặn ở bước chạy thử, không lưu nến nào, và **gợi ý đúng `Europe/Athens`**.
- Lỗi phát hiện và đã sửa khi soát:
  1. Gợi ý "độ lệch cố định" sai khi lịch sử trải qua đổi giờ → đổi sang thử tên múi giờ IANA.
  2. Chạy thử chỉ trên 2.000 nến không phân biệt được giờ mùa hè → chạy thử toàn bộ lịch sử theo lô.
  3. Hướng dẫn từng bảo bật "Allow algorithmic trading" (không cần cho việc chỉ đọc) → đã bỏ.
  4. nginx giới hạn 1 MB → nâng lên 5 MB.
  5. Giao diện chờ 10 giây mới hiện trạng thái Gateway → hỏi lại ngay khi biết nguồn là MT5.

## 8. Giới hạn v1

- Chưa có hàng đợi bền vững trên đĩa (vòng lặp gửi lại 20 nến gần nhất nên không mất dữ liệu khi gián đoạn ngắn; gián đoạn > 5 giờ thì cần chạy lại để nạp bù).
- Chưa đóng gói `.exe` (PyInstaller phải build trên Windows). v1 chạy bằng `uv`, tự tải Python.
- Chưa dùng lịch giao dịch riêng của broker.
- **Chưa chạy trên MT5 thật trong môi trường phát triển.** Lần chạy đầu tiên của người dùng là lần kiểm chứng thật đầu tiên.
