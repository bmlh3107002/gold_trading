# MT5 Gateway (bản CHỈ ĐỌC): hướng dẫn chạy trên Windows

Gateway đọc nến **XAUUSD M15** từ MetaTrader 5 và gửi vào hệ thống đang chạy bằng Docker.

> 🔒 **Gateway này KHÔNG thể đặt, sửa hay hủy lệnh.** Mã nguồn không có hàm giao dịch nào, và có test tự động kiểm tra điều đó. Dù vậy, khi thử nghiệm vẫn nên dùng **tài khoản demo**.

Cần có: máy **Windows**, **Docker Desktop** đang chạy, **MetaTrader 5** đã đăng nhập tài khoản demo.

---

## Bước 1: Chuẩn bị MetaTrader 5

1. Mở MT5 và đăng nhập tài khoản **demo**. Góc dưới bên phải phải hiện tốc độ kết nối, không được hiện "No connection".
2. Mở **Market Watch** (Ctrl+M) và kiểm tra có dòng **XAUUSD**. Nếu không thấy: chuột phải → **Show All**.
3. **Tools → Options → Charts → Max bars in chart**, chọn **Unlimited**, bấm OK.
4. Mở một chart **XAUUSD**, chọn khung **M15**, và cuộn về bên trái vài lần để MT5 tải lịch sử.

> **Không cần** bật "Allow algorithmic trading" (nút **Algo Trading**). Gateway chỉ đọc dữ liệu nên không cần quyền giao dịch tự động. Hãy để **tắt**.

## Bước 2: Lấy token cho Gateway

Token là "mật khẩu" để chỉ Gateway của bạn mới gửi được dữ liệu vào **đúng tài khoản giao dịch**.

- **Cách mới (khuyên dùng, DEC-16):** token được sinh tự động khi `admin` tạo người dùng trên Dashboard (**Quản trị → Tạo người dùng**) và hiện **một lần** ngay sau đó → bấm **Sao chép**. Mất token: `admin` bấm **Quản trị → Cấp lại token** ở dòng người dùng đó. Mỗi lần cấp token mới, token cũ hết hiệu lực ngay (kể cả `GT_INGEST_TOKEN` trong `.env` của Docker), nên phải dán token mới vào `gateway.env` (Bước 4) rồi chạy lại Gateway. Người dùng bị khóa → Gateway của họ nhận `HTTP 403`.
- **Cách cũ (vẫn chạy được cho "Tài khoản chính" tới lần tạo token đầu tiên trên Dashboard):** tạo chuỗi ngẫu nhiên bằng PowerShell `[guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")`, dán vào `GT_INGEST_TOKEN` ở cả `.env` của Docker (Bước 3) và `gateway.env` (Bước 4).

Không gửi token qua chat hay email.

## Bước 3: Cấu hình Docker dùng dữ liệu MT5

1. Tải lại file `docker-compose.yml` mới nhất (cách tải như trong `deploy/README.md`), đặt vào thư mục bạn đang dùng cho Docker.
2. Trong **cùng thư mục đó**, tạo file tên **`.env`** (có dấu chấm ở đầu) với nội dung:

   ```text
   GT_DATA_SOURCE=MT5
   GT_INGEST_TOKEN=<dán token ở bước 2>
   GT_BROKER_SESSIONS=Mon-Fri 00:00-23:00
   GT_BROKER_SERVER_TZ=Europe/Athens
   ```

   Hai dòng cuối là **giờ báo giá của broker**. Lấy trong MT5: Market Watch → chuột phải XAUUSD → **Specification** → kéo xuống **Sessions**, chép cột **Quotes** (giờ server). Ví dụ trên là của MetaQuotes-Demo. `GT_BROKER_SERVER_TZ` phải giống `GT_SERVER_TZ` ở Bước 4. Thiếu hai dòng này thì phân tích kỹ thuật có thể bị chặn vì "thiếu nến" ở giờ broker nghỉ.

3. Chạy:

   ```powershell
   docker compose up -d --build
   ```

4. Mở http://localhost:8080. Trang **Thị trường** sẽ báo "Chưa có nến nào". Đây là bình thường, vì Gateway chưa chạy.

## Bước 4: Tải và cấu hình Gateway

1. Trên GitHub, vào repo → nút xanh **Code → Download ZIP**, rồi giải nén.
2. Mở thư mục **`mt5_gateway`** bên trong.
3. Copy file **`gateway.env.example`** thành **`gateway.env`** (cùng thư mục), mở bằng Notepad và sửa:

   ```text
   GT_INGEST_TOKEN=<dán CÙNG token ở bước 2>
   GT_BROKER_SYMBOL=XAUUSD
   GT_SERVER_TZ=Europe/Athens
   ```

   `Europe/Athens` đúng với đa số broker (giờ server GMT+2 mùa đông, GMT+3 mùa hè). Nếu sai, bước 6 sẽ báo và gợi ý múi giờ đúng.

## Bước 5: Cài `uv` (chỉ làm một lần)

`uv` tự tải đúng phiên bản Python mà Gateway cần; bạn không phải tự cài Python. Trong PowerShell chạy:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Sau đó **đóng và mở lại PowerShell**.

## Bước 6: Chạy kiểm tra

Trong PowerShell, chuyển vào thư mục `mt5_gateway` (thay đường dẫn cho đúng chỗ bạn giải nén):

```powershell
cd "C:\Users\<tên bạn>\Downloads\gold_trading-develop\mt5_gateway"
```

```powershell
uv run mt5-gateway check
```

Lần đầu sẽ mất 1–2 phút để tải Python và thư viện. Kết quả mong muốn là **tất cả các dòng ĐẠT**, và cuối cùng là `KẾT QUẢ: SẴN SÀNG`:

```text
[  ĐẠT   ] 1. Cấu hình múi giờ server: Europe/Athens (hiện tại GMT+2)
[  ĐẠT   ] 2. Token: Đã đặt (64 ký tự)
[  ĐẠT   ] 3. Kết nối MT5: ...
[  ĐẠT   ] 4. Tài khoản: DEMO · ...
[  ĐẠT   ] 5. Symbol: XAUUSD: digits 2, contract 100, lot tối thiểu 0.01, bước lot 0.01
[  ĐẠT   ] 6. Giờ server (tick trực tiếp): Khớp: GMT+2
[  ĐẠT   ] 7. Lịch sử nến M15: ... nến đã đóng ...
[  ĐẠT   ] 8. Backend: http://localhost:8080 · lưu trữ postgres
[  ĐẠT   ] 9. Chạy thử gửi dữ liệu (không lưu): ...
[  ĐẠT   ] 10. Liên kết MT5: Đã liên kết đúng MT5 này
[  ĐẠT   ] 11. Khung H1/H4/D1: H1 ... nến; H4 ... nến; D1 ... nến
[  ĐẠT   ] 12. Giá sống (bid/ask): 59 giây có giá trong 60 giây qua; gần nhất bid ... / ask ...
[  ĐẠT   ] 13. Cặp tiền chỉ số USD: Đủ 6/6: EURUSD, USDJPY, GBPUSD, USDCAD, USDSEK, USDCHF
KẾT QUẢ: SẴN SÀNG. Chạy: mt5-gateway run
```

- Dòng 12 (giá sống, Gateway ≥ 0.7.0) hiện **CẢNH BÁO** khi thị trường đóng cửa/yên (bình thường, giá sống tự gửi khi có tick) hoặc khi MT5 trả tick sai khoảng thời gian (khi đó **không** gửi giá sống, nến vẫn chạy — gửi lại kết quả check để được hỗ trợ).
- Dòng 13 (Gateway ≥ 0.8.0) hiện **CẢNH BÁO** nếu MT5 thiếu cặp tiền nào: Market Watch (Ctrl+M) → chuột phải → **Show All**, rồi chạy lại `check`. Broker đặt tên khác thì ghi `GT_USD_PAIRS` trong `gateway.env` (xem `gateway.env.example`). Thiếu cặp chỉ làm chỉ số USD (làm ở bước sau) báo "không đủ dữ liệu"; vàng vẫn chạy.
- Dòng 11 hiện **CẢNH BÁO** nếu MT5 chưa có lịch sử khung đó: mở chart XAUUSD ở khung H1, H4, D1 (mỗi khung một lần) rồi chạy lại `check`. Khung bị cảnh báo sẽ không được gửi; M15 vẫn chạy.
- Dòng 6 hiện **CẢNH BÁO** khi thị trường đóng cửa (cuối tuần) là bình thường; dòng 9 vẫn kiểm tra múi giờ bằng lịch sử. Tốt nhất nên chạy khi thị trường mở.
- Nếu có dòng **LỖI**, xem gợi ý "→ Cách xử lý" ngay bên dưới dòng đó. **Hãy copy toàn bộ kết quả gửi lại để được hỗ trợ.**

Lệnh `check` **không ghi dữ liệu** gì vào hệ thống.

## Bước 7: Chạy đồng bộ

```powershell
uv run mt5-gateway run
```

- Gateway chạy lại `check`. Chỉ khi tất cả đạt, nó mới nạp khoảng 5.000 nến lịch sử (khoảng 2 tháng), sau đó cứ 5 giây gửi các nến vừa đóng.
- **Lần đầu (hoặc sau khi gỡ liên kết):** nến chỉ được ghi khi MT5 đã **liên kết**. Gateway in `Chưa gửi nến: MT5_LINK_REQUIRED …` và **vẫn chạy tiếp** (không tắt). Mở web → trang **Tài khoản** → thẻ **Liên kết MT5** → gõ lại số login → bấm **Xác nhận đây là MT5 của tôi**. Khoảng 30 giây sau Gateway tự nạp lịch sử.
- **Đổi sang MT5 khác trong terminal khi đang chạy:** hệ thống **ngừng ghi** (`MT5_LINK_MISMATCH`), không tự chuyển. Đăng nhập lại MT5 cũ rồi bấm **Xác minh lại** trên web, hoặc **Gỡ liên kết** rồi xác nhận MT5 mới.
- **Để cửa sổ PowerShell mở.** Muốn dừng thì bấm **Ctrl+C**.
- Trên http://localhost:8080:
  - chân sidebar hiện **"MT5: đã kết nối · demo"**;
  - trang Thị trường hiện giá thật, **không còn nhãn "Dữ liệu mẫu"**;
  - khoảng 15 giây sau khi có dữ liệu, thẻ Phân tích kỹ thuật sẽ có kết quả.

---

## Nhiều MT5 trên một máy (MT-15, Gateway 0.6.0)

Dùng khi máy chạy **nhiều MetaTrader 5 cùng lúc**, mỗi MT5 cho một tài khoản giao dịch (một người dùng). Một cửa sổ Gateway trông coi tất cả; bên trong mỗi MT5 chạy một tiến trình riêng (thư viện MetaTrader5 chỉ nối được một MT5 mỗi tiến trình).

1. Mỗi MT5 phải cài ở **thư mục riêng** (khi cài, chọn thư mục khác, ví dụ `C:\MT5\LordTrade`, `C:\MT5\Exness`). Mở từng MT5 và đăng nhập đúng tài khoản.
2. Trong thư mục `mt5_gateway`, mở thư mục **`terminals`**. Copy `vi-du.env.example` thành **một file cho mỗi MT5**, ví dụ `lordtrade.env`, `exness.env`. Trong mỗi file sửa:
   - `GT_INGEST_TOKEN`: token của **đúng** người dùng dùng MT5 đó. Mỗi file một token **khác nhau**.
   - `GT_MT5_PATH`: đường dẫn `terminal64.exe` của **đúng** MT5 đó (chuột phải biểu tượng MT5 → **Open file location**).
3. Kiểm tra tất cả:

   ```powershell
   uv run mt5-gateway check-all
   ```

4. Chạy tất cả (để cửa sổ mở, Ctrl+C dừng tất cả):

   ```powershell
   uv run mt5-gateway run-all
   ```

Mỗi dòng log có tên MT5 ở đầu, ví dụ `[exness]`. An toàn:

- Hai file **chung token**, hai file trỏ **cùng một MT5**, thiếu `GT_MT5_PATH`, sai đường dẫn → **không chạy MT5 nào**, in rõ file nào sai.
- Gateway kiểm terminal đang nối đúng thư mục trong `GT_MT5_PATH`; nối nhầm MT5 khác → `TERMINAL_MISMATCH`, không gửi nến của MT5 đó.
- Một MT5 lỗi (chưa mở, mất mạng, check chưa đạt) thì chỉ MT5 đó dừng và tự chạy lại sau 30 giây (lâu dần tới 5 phút); các MT5 khác vẫn chạy.
- Biến môi trường `GT_*` của Windows bị bỏ qua: mỗi MT5 chỉ dùng file của nó.
- Đừng chạy thêm `mt5-gateway run` riêng cho một MT5 đang có trong `run-all`.

Mỗi người dùng vẫn phải **xác nhận liên kết MT5** trên trang Tài khoản của mình (như Bước 7).

---

## Lỗi thường gặp

| Thông báo | Cách xử lý |
| --- | --- |
| `Không tìm thấy thư viện MetaTrader5` | Gateway phải chạy trên Windows. Chạy lại `uv run mt5-gateway check` |
| `Kết nối MT5 (initialize) thất bại` | Mở MT5 và đăng nhập trước. Nếu máy cài nhiều MT5, đặt `GT_MT5_PATH` trong `gateway.env` trỏ tới `terminal64.exe` |
| `Không tìm thấy XAUUSD` | Đặt `GT_BROKER_SYMBOL` đúng tên trong Market Watch (ví dụ `XAUUSDm`, `XAUUSD.r`) |
| `Chỉ có ... nến` | Làm lại Bước 1, mục 3 và 4 |
| `Không kết nối được backend` | Kiểm tra Docker đang chạy và mở được http://localhost:8080 |
| `HTTP 503` / `chưa đặt GT_INGEST_TOKEN` | Thiếu file `.env` ở Bước 3, hoặc chưa chạy lại `docker compose up -d` |
| `HTTP 401` / `Token không hợp lệ` | Token ở `gateway.env` sai, hoặc đã tạo token mới trên Dashboard (token cũ hết hiệu lực): dán token mới vào `gateway.env` |
| `HTTP 403` / `đang bị khóa` | Người dùng của tài khoản này bị `admin` khóa: mở khóa trên **Quản trị**, token cũ dùng lại được |
| `HTTP 403` / `chưa được phép ghi nến dùng chung` | Token thuộc tài khoản giao dịch không phải "Tài khoản chính". Tới GĐ1 chỉ tài khoản chính được ghi nến |
| `HTTP 503` / `đồng hồ máy chủ lệch` | Đồng hồ máy chạy Docker lệch > 30 giây: khởi động lại Docker Desktop (hay gặp sau khi máy ngủ) |
| `Múi giờ ... không khớp` | Làm theo gợi ý `Đặt GT_SERVER_TZ=...` rồi chạy lại `check` |
| `MT5_LINK_REQUIRED` | MT5 chưa liên kết (hoặc Gateway bản cũ < 0.4.0): xác nhận MT5 trên trang **Tài khoản**; Gateway tự gửi tiếp, không cần chạy lại |
| `MT5_LINK_SYMBOL` | Đã đổi `GT_BROKER_SYMBOL` (symbol khác = nguồn giá khác): đặt lại như cũ, hoặc **Gỡ liên kết** trên web rồi xác nhận lại để dùng symbol mới |
| `MT5_LINK_MISMATCH` | Terminal đang đăng nhập MT5 khác MT5 đã liên kết: xem thẻ **Liên kết MT5** trên trang Tài khoản |
| `SERVER_TZ_SUSPECT` / `SERVER_TZ_CHANGED` | Giờ server broker vừa lệch khác `GT_SERVER_TZ` khi đang chạy: Gateway **tạm ngừng gửi nến + giá** để không lưu sai giờ. Lệch thoáng qua thì tự chạy tiếp. Nếu broker đổi giờ thật: chạy lại `check`, làm theo gợi ý sửa `GT_SERVER_TZ` |
| `Tắt gửi giá sống` | Giá sống tạm tắt (nến vẫn chạy). Nếu ghi "cần cập nhật backend": cập nhật Docker (`docker compose build --no-cache backend frontend`) |
| `TERMINAL_MISMATCH` | Gateway nối vào MT5 khác với `GT_MT5_PATH`: sửa đường dẫn cho đúng `terminal64.exe` của MT5 này, và mỗi MT5 cài ở thư mục riêng |
| `dùng CHUNG một token` / `CÙNG một terminal` (run-all) | Mỗi file trong `terminals` phải có token riêng và trỏ tới MT5 riêng |
| Cảnh báo `TÀI KHOẢN THẬT` | Gateway vẫn chỉ đọc, nhưng nên đổi sang tài khoản demo khi thử nghiệm |

## Giới hạn của bản này

- Đây là **lần đầu chạy với MT5 thật**: Gateway đã được test kỹ với MT5 giả lập, nhưng chưa chạy trên MT5 thật. Nếu có lỗi lạ, gửi lại toàn bộ kết quả `check` hoặc log.
- Chưa chạy nền như một dịch vụ của Windows (phải để cửa sổ PowerShell mở) và chưa đóng gói `.exe`.
- Backend hoặc mạng mất lâu trong lúc Gateway vẫn chạy: khi thông lại, Gateway tự đọc lùi lịch sử MT5 và gửi bù đủ nến (Gateway ≥ 0.8.1). Nếu gián đoạn dài hơn `GT_HISTORY_BARS` nến M15 (mặc định 5.000 ≈ 2 tháng), log báo "có thể THIẾU nến": tăng `GT_HISTORY_BARS` rồi chạy lại `run`.
