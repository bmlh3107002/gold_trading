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
