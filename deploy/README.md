# Chạy Gold Trading bằng Docker (không cần clone code)

Một lệnh `docker compose up` sẽ chạy đủ 3 thành phần: **giao diện** (AurumDesk), **backend** (API) và **database** (PostgreSQL/TimescaleDB).

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

## 3. Chạy

Mở terminal trong thư mục đó:

```bash
docker compose up -d --build
```

Lần đầu mất vài phút để Docker tải code từ GitHub và build. Xong thì mở **http://localhost:8080**.

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

- Dashboard chỉ mở ở `localhost`. API **chưa có xác thực**, đừng mở cổng ra mạng ngoài.
- Dữ liệu (lịch sử Safety, Mode, audit) lưu trong volume `db_data`, không mất khi restart hay `down`. Chỉ `down -v` mới xóa.
- Sau mỗi lần khởi động lại: nếu trước đó **ACTIVE** thì tự về **PAUSED** (phải bấm "Cho phép giao dịch" lại); **HALTED** được giữ nguyên; **LIVE** tự về **PAPER**.
- Database không mở cổng ra máy. Mật khẩu mặc định `gold-local-only` chỉ dùng trong mạng nội bộ của Docker; muốn đổi thì tạo file `.env` cạnh `docker-compose.yml` với `POSTGRES_PASSWORD=...` **trước lần chạy đầu tiên** (đổi sau khi DB đã tạo sẽ không có tác dụng trừ khi `down -v`).
- **MT5 Gateway và Guardian EA không chạy trong Docker.** Chúng cần terminal MetaTrader 5 trên Windows và sẽ có hướng dẫn riêng khi làm tới.
- Nếu repo chuyển sang private, Docker sẽ không tự tải được code nữa. Khi đó cần cách khác (ví dụ image dựng sẵn trên GHCR).
