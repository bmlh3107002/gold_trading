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
- **Liên kết (MT-13, 2026-11-07):** danh tính trong nhịp tim tạo liên kết chờ xác nhận ở bảng `mt5_links` (xem `00-xac-thuc-phan-quyen.md` mục 14.5). **Chưa làm:** chuyển MISMATCH/chặn ghi khi đổi tài khoản (MT-14). Hiện tại terminal đăng xuất vẫn hiện CONNECTED nếu Gateway còn đọc được nến (chỉ `identity: null`) — MT-14 xử lý.

## 6. Lệnh cho người dùng

- `mt5-gateway check`: chẩn đoán từng bước, mỗi bước báo **ĐẠT / LỖI** kèm cách sửa. Không ghi dữ liệu.
- `mt5-gateway run`: chạy `check` trước; tất cả đạt mới bắt đầu đồng bộ.

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
