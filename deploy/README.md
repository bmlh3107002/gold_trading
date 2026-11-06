# Chạy Gold Trading bằng Docker (không cần clone code)

Một lệnh `docker compose up` sẽ chạy đủ các thành phần: **giao diện** (CutlotDesk), **backend** (API), **database** (PostgreSQL/TimescaleDB), **Keycloak** (đăng nhập, có database riêng) và **backup** (sao lưu tự động).

Chỉ cần cài **Docker Desktop**. Không cần Python, Node hay git.

## 1. Cài Docker Desktop

Tải ở https://www.docker.com/products/docker-desktop/ (Windows / macOS), cài xong thì mở Docker Desktop lên và đợi biểu tượng báo "running".

## 2. Tải file compose

Tạo một thư mục trống, ví dụ `gold-trading`, rồi tải file [`docker-compose.yml`](docker-compose.yml) vào đó.
Trên GitHub, mở file này, bấm nút **Download raw file**. Hoặc dùng lệnh:

macOS / Linux:

```bash
mkdir gold-trading && cd gold-trading && curl -fsSLO https://raw.githubusercontent.com/bmlh3107002/gold_trading/develop/deploy/docker-compose.yml
```

Windows (PowerShell):

```powershell
mkdir gold-trading; cd gold-trading; curl.exe -fsSLO https://raw.githubusercontent.com/bmlh3107002/gold_trading/develop/deploy/docker-compose.yml
```

## 3. Tạo file `.env` chứa bí mật (chỉ làm một lần)

Hệ thống cần vài mật khẩu ngẫu nhiên (mật khẩu database Keycloak, mật khẩu quản trị Keycloak, "client secret" giữa backend và Keycloak). **Không gõ tay, không gửi cho ai.** Mở PowerShell **trong thư mục chứa `docker-compose.yml`** và chạy (dán nguyên khối):

```powershell
function New-Secret { $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_') }
Add-Content -Encoding ascii .env "KC_DB_PASSWORD=$(New-Secret)"
Add-Content -Encoding ascii .env "KC_ADMIN_PASSWORD=$(New-Secret)"
Add-Content -Encoding ascii .env "GT_OIDC_CLIENT_SECRET=$(New-Secret)"
Add-Content -Encoding ascii .env "GT_ADMIN_USERNAME=admin"
Add-Content -Encoding ascii .env "GT_PUBLIC_URL=http://localhost:8080"
Write-Host "Da them bi mat vao .env (khong in ra man hinh)"
```

Thêm **mật khẩu tạm** để đăng nhập lần đầu (bạn sẽ phải đổi ngay khi đăng nhập). Lệnh dưới hỏi mật khẩu và không hiện ra màn hình:

```powershell
$p = Read-Host "Mat khau tam (it nhat 12 ky tu)" -AsSecureString; Add-Content -Encoding ascii .env ("GT_ADMIN_INITIAL_PASSWORD=" + [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p)))
```

> Đã có file `.env` từ trước (ví dụ có `GT_DATA_SOURCE=MT5`, `GT_INGEST_TOKEN`, `GT_BROKER_...`) thì cứ giữ nguyên, các lệnh trên chỉ **thêm** dòng mới. Nếu có dòng `DASHBOARD_BIND=100.x.y.z` thì **xóa dòng đó** (giờ dùng Tailscale Serve, xem bên dưới).

Thiếu biến nào thì `docker compose` báo lỗi rõ (ví dụ *Thiếu KC_DB_PASSWORD trong .env*) và không chạy.

## 4. Chạy

```bash
docker compose up -d --build
```

Lần đầu mất vài phút (Docker tải code từ GitHub và build; Keycloak khởi động khoảng 1–2 phút). Xong thì mở **http://localhost:8080**.

## 5. Đăng nhập lần đầu

1. Mở địa chỉ trong `GT_PUBLIC_URL` (mặc định http://localhost:8080), bấm **Đăng nhập**.
2. Trang đăng nhập Keycloak: tên `admin` (hoặc `GT_ADMIN_USERNAME`), mật khẩu tạm ở bước 3.
3. Keycloak yêu cầu **đặt mật khẩu mới** (ít nhất 12 ký tự), rồi **bổ sung email và họ tên**.
4. Bạn được đưa về Dashboard, trang **Quản trị**. Tài khoản `admin` **chỉ quản lý người dùng**, không giao dịch (DEC-16). Vào **Quản trị → Tạo người dùng** để tạo người giao dịch: người dùng đầu tiên nhận "Tài khoản chính" (nguồn giá). Hệ thống hiện **token Gateway** (và mật khẩu tạm nếu để trống) **một lần**: lưu lại ngay.

- Sai mật khẩu nhiều lần, Keycloak sẽ **khóa tạm** (tối đa 15 phút).
- Phiên đăng nhập tối đa 8 giờ; không thao tác 30 phút thì hết phiên. Khởi động lại backend thì phải đăng nhập lại.
- Trang quản trị Keycloak (quản lý người dùng): `<GT_PUBLIC_URL>/auth/admin/`, tài khoản `kcadmin`, mật khẩu là `KC_ADMIN_PASSWORD` trong `.env`. **Chưa tạo thêm người dùng** cho tới khi có ý kiến pháp lý (DEC-12); hệ thống cũng sẽ từ chối thêm người thứ hai vào tài khoản giao dịch.

## Lệnh thường dùng

| Việc | Lệnh |
| --- | --- |
| Cập nhật lên code mới nhất của `develop` | `docker compose up -d --build` |
| Xem log | `docker compose logs -f` |
| Xem trạng thái | `docker compose ps` |
| Dừng (giữ dữ liệu) | `docker compose down` |
| Dừng và **xóa toàn bộ dữ liệu** | `docker compose down -v` |
| Đổi cổng dashboard | `DASHBOARD_PORT=9000 docker compose up -d --build` |
| Chạy nhánh khác | `GT_BRANCH=main docker compose up -d --build` |
| Đổi địa chỉ truy cập / client secret sau lần chạy đầu | sửa `.env`, `docker compose up -d`, rồi `docker compose exec keycloak /opt/keycloak/bin/sync-client.sh` |
| **Dừng khẩn cấp khi không đăng nhập được** | `docker compose exec backend gt-break-glass halt --all --reason KEYCLOAK_DOWN` |
| Xem trạng thái Safety không cần đăng nhập | `docker compose exec backend gt-break-glass status` |
| Sao lưu ngay | `docker compose exec backup /usr/local/bin/gt/backup.sh once` |

## Truy cập từ điện thoại / máy khác (HTTPS qua Tailscale Serve)

Đăng nhập dùng cookie bảo mật nên **bắt buộc HTTPS** khi mở từ máy khác. Tailscale Serve cấp HTTPS miễn phí, chỉ máy trong mạng Tailscale của bạn vào được. Dashboard vẫn chỉ mở ở `127.0.0.1`.

1. Trang quản trị Tailscale (https://login.tailscale.com/admin/dns): bật **MagicDNS** và **HTTPS Certificates**.
2. Trên máy chạy Docker, PowerShell: `tailscale serve --bg http://127.0.0.1:8080`
3. Xem địa chỉ: `tailscale serve status` → dạng `https://<tên-máy>.<tailnet>.ts.net`
4. Trong `.env`: đổi `GT_PUBLIC_URL=https://<tên-máy>.<tailnet>.ts.net` (không có `/` ở cuối) và xóa dòng `DASHBOARD_BIND` nếu có.
5. `docker compose up -d`, rồi (nếu Keycloak đã chạy trước đó với địa chỉ cũ) `docker compose exec keycloak /opt/keycloak/bin/sync-client.sh`.
6. Mở `https://<tên-máy>.<tailnet>.ts.net` trên máy tính và điện thoại (điện thoại phải bật Tailscale).

- Backend từ chối khởi động nếu `GT_PUBLIC_URL` là `http://` mà không phải `localhost`.
- Sau khi đặt địa chỉ `ts.net`, mở `http://localhost:8080` vẫn được, nhưng khi đăng nhập sẽ được chuyển sang địa chỉ `ts.net`.
- **Không** dùng `DASHBOARD_BIND=0.0.0.0`.

## Dừng khẩn cấp khi Keycloak hỏng (break-glass)

Nếu không đăng nhập được (Keycloak lỗi, quên mật khẩu...), vẫn **dừng giao dịch** được bằng lệnh trên máy chạy Docker:

```powershell
docker compose exec backend gt-break-glass halt --all --reason KEYCLOAK_DOWN
```

- Lệnh này **chỉ dừng** (HALT), không bao giờ mở lại giao dịch hay bật LIVE. Muốn mở lại phải đăng nhập Dashboard với vai trò Chủ.
- Dừng một tài khoản: `--account default` thay cho `--all`. Xem trạng thái: `gt-break-glass status`.
- Backend đang chạy nhận trạng thái mới trong khoảng 2 giây; nhật ký ghi người thực hiện là `break-glass`.

## Sao lưu và khôi phục

Container `backup` tự sao lưu **DB ứng dụng và DB Keycloak** mỗi 24 giờ (lần đầu sau khi khởi động 5 phút), giữ **14 bản** mỗi DB, ở thư mục **`backups\`** cạnh `docker-compose.yml` (đổi bằng `GT_BACKUP_DIR` trong `.env`). Dashboard cảnh báo nếu sao lưu lỗi, quá 26 giờ chưa có bản mới, hoặc ổ đĩa dùng trên 85%.

- Bản sao lưu chứa dữ liệu nhạy cảm (hash mật khẩu, client secret). Nên chép thêm ra ổ khác/USB định kỳ, đừng gửi lên mạng.

**Khôi phục** (ví dụ khi mất volume DB, ổ hỏng):

```powershell
docker compose stop backend keycloak
docker compose run --rm backup restore app latest
docker compose run --rm backup restore keycloak latest
docker compose up -d
```

- Thay `latest` bằng tên file (ví dụ `app-20261106T030000Z.dump`) để chọn bản cụ thể.
- Script kiểm tra SHA-256 và **từ chối** nếu file hỏng hoặc backend/keycloak còn chạy.
- Sau khi khôi phục, nếu trước đó đang **ACTIVE** thì hệ thống tự về **PAUSED**: phải kiểm tra rồi bấm mở lại.

## Bật xác thực 2 lớp (khi muốn)

Chưa bật theo lựa chọn của người dùng (2026-11-06). Bật sau, không cần sửa code: trang quản trị Keycloak → realm **gold-trading** → **Authentication** → **Required actions** → bật **Configure OTP** làm mặc định ("Set as default action"). Lần đăng nhập tới, Keycloak hiện mã QR để quét bằng Google Authenticator / Microsoft Authenticator.

## Dữ liệu giá

Mặc định hệ thống chạy với **dữ liệu mẫu** (`GT_DATA_SOURCE=SAMPLE`): khoảng 90 ngày nến XAUUSD M15 được sinh tự động, và cứ mỗi nến M15 đóng thì có thêm một nến mới. Giao diện luôn gắn nhãn **"Dữ liệu mẫu"**, đồng thời chế độ **SHADOW và LIVE bị khóa**.

> Dữ liệu mẫu chỉ để kiểm thử giao diện và hệ thống. **Không dùng để đánh giá chiến lược hay ra quyết định giao dịch.**

### Nạp file CSV xuất từ MT5

1. Trên MT5: mở **View → Symbols** (hoặc Ctrl+U), chọn XAUUSD, vào tab **Bars**, chọn khung **M15** và khoảng thời gian, bấm **Request** rồi **Export Bars**.
2. Tìm **múi giờ server của broker**. MT5 xuất theo giờ server chứ không phải UTC. Phần lớn broker dùng GMT+2 vào mùa đông và GMT+3 vào mùa hè, khi đó khai báo `Europe/Athens`. Nếu không chắc, hãy hỏi broker hoặc so giờ trên MT5 với giờ UTC.
3. Nạp vào hệ thống (chạy trong thư mục chứa `docker-compose.yml`):

```bash
docker compose cp XAUUSD_M15.csv backend:/tmp/data.csv
```

```bash
docker compose exec backend python -m gold_trading.ingestion.cli import-csv /tmp/data.csv --server-tz Europe/Athens
```

Muốn xem thử trước mà không ghi gì thì thêm `--dry-run`. Nạp lại cùng một file sẽ không bị nhân đôi dữ liệu. Dòng lỗi được đưa vào khu cách ly, có thể xem ở mục "Chất lượng dữ liệu" trên trang Thị trường.

4. Chuyển Dashboard sang dùng dữ liệu CSV: tạo file `.env` cạnh `docker-compose.yml` với nội dung `GT_DATA_SOURCE=CSV`, rồi chạy `docker compose up -d`.

### Lấy dữ liệu trực tiếp từ MT5 (Windows)

Xem hướng dẫn từng bước ở [`mt5_gateway/README.md`](../mt5_gateway/README.md). Tóm tắt: tạo file `.env` cạnh `docker-compose.yml` với `GT_DATA_SOURCE=MT5` và `GT_INGEST_TOKEN=<token>`, rồi chạy `docker compose up -d`. Sau đó chạy MT5 Gateway với cùng token. Gateway **chỉ đọc**, không đặt lệnh.

## Tìm các thành phần trong Docker Desktop

Mọi thứ được gom dưới project **`gold_trading`**:

| Loại | Tên |
| --- | --- |
| Nhóm container (tab *Containers*) | `gold_trading` → `gold_trading-db-1`, `gold_trading-backend-1`, `gold_trading-frontend-1` |
| Image tự build (tab *Images*) | `gold_trading/backend`, `gold_trading/frontend` |
| Image database tải về | `timescale/timescaledb` |
| Dữ liệu (tab *Volumes*) | `gold_trading_db_data` |

Lọc nhanh bằng lệnh:

```bash
docker images "gold_trading/*"
```

```bash
docker compose ls
```

Mỗi lần `up --build` sẽ để lại image cũ không tên (`<none>`). Dọn bằng:

```bash
docker image prune -f
```

Gỡ **toàn bộ** dự án khỏi máy (container, image tự build, dữ liệu):

```bash
docker compose down -v --rmi local
```

## Lưu ý

- Dashboard chỉ mở ở `localhost`; truy cập từ máy khác qua Tailscale Serve (HTTPS). Mọi API đều cần đăng nhập (trừ cổng Gateway dùng token riêng).
- Dữ liệu lưu trong volume `db_data` (ứng dụng) và `keycloak_db_data` (đăng nhập), không mất khi restart hay `down`. Chỉ `down -v` mới xóa — khi đó khôi phục từ thư mục `backups\`.
- Sau mỗi lần khởi động lại: nếu trước đó **ACTIVE** thì tự về **PAUSED** (phải bấm "Cho phép giao dịch" lại); **HALTED** được giữ nguyên; **LIVE** tự về **PAPER**.
- Database không mở cổng ra máy. Mật khẩu mặc định `gold-local-only` chỉ dùng trong mạng nội bộ của Docker; muốn đổi thì tạo file `.env` cạnh `docker-compose.yml` với `POSTGRES_PASSWORD=...` **trước lần chạy đầu tiên** (đổi sau khi DB đã tạo sẽ không có tác dụng trừ khi `down -v`).
- **MT5 Gateway không chạy trong Docker** (cần MetaTrader 5 trên Windows): xem `mt5_gateway/README.md`. Token của Gateway do hệ thống sinh khi `admin` tạo người dùng; mất token thì `admin` bấm **Quản trị → Cấp lại token** (token cũ chết ngay). Token cũ `GT_INGEST_TOKEN` trong `.env` chỉ còn dùng được tới khi "Tài khoản chính" có token đầu tiên.
- Log mỗi container giới hạn 5 file × 10 MB, dạng JSON, đã che token/mật khẩu/cookie.
- Nếu repo chuyển sang private, Docker sẽ không tự tải được code nữa. Khi đó cần cách khác (ví dụ image dựng sẵn trên GHCR).
