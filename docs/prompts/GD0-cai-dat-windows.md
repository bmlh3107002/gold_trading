# Prompt: Hướng dẫn cài đặt GĐ0 trên máy Windows mới (tiếp tục)

> Dán phần dưới đường kẻ vào một phiên Claude Code mới trên repo `bmlh3107002/gold_trading`, nhánh `develop`.

---

Đọc `CLAUDE.md`, `PROGRESS.md`, `deploy/README.md` và `mt5_gateway/README.md`. Code GĐ0 đã xong và CI đã xanh. Việc còn lại để đạt Gate GĐ0 là **hướng dẫn người dùng cài trên máy Windows mới và diễn tập**.

Người dùng không rành kỹ thuật: giải thích đơn giản bằng tiếng Việt, **mỗi lần chỉ đưa một bước**, đợi người dùng báo kết quả rồi mới sang bước tiếp. Mỗi lệnh PowerShell để trong một khối riêng và chỉ dùng ký tự ASCII trong lệnh. Không bao giờ yêu cầu dán mật khẩu, token hay nội dung `.env` vào chat; lệnh kiểm tra chỉ in tên biến hoặc che bí mật.

## Đã làm (máy Windows mới, thư mục `C:\gold-trading`)

1. Đã cài Docker Desktop (`Docker version 29.9.2`).
2. Đã tải `C:\gold-trading\docker-compose.yml` (7.334 byte, khớp `deploy/docker-compose.yml` trên `develop`).
3. **Đang làm:** tạo `.env` bằng lệnh PowerShell sinh bí mật ngẫu nhiên. Các biến: `KC_DB_PASSWORD`, `KC_ADMIN_PASSWORD`, `GT_OIDC_CLIENT_SECRET`, `POSTGRES_PASSWORD`, `GT_ADMIN_USERNAME=admin`, `GT_PUBLIC_URL=http://localhost:8080`, `GT_DATA_SOURCE=MT5`, `GT_BROKER_SESSIONS=Mon-Fri 00:00-23:00`, `GT_BROKER_SERVER_TZ=Europe/Athens`. Hỏi người dùng đã chạy chưa, và kiểm tra bằng lệnh chỉ in tên biến: `Get-Content .env | ForEach-Object { ($_ -split '=')[0] }` (đúng là 9 tên).

## Các bước tiếp theo (mỗi lần một bước)

4. Thêm mật khẩu tạm đăng nhập lần đầu `GT_ADMIN_INITIAL_PASSWORD` bằng `Read-Host -AsSecureString` (xem `deploy/README.md` mục 3).
5. `docker compose up -d --build`, đợi rồi kiểm tra `docker compose ps` (backend và keycloak healthy). Lần đầu mất vài phút.
6. Mở http://localhost:8080 → Đăng nhập → `admin` + mật khẩu tạm → đặt mật khẩu mới (≥ 12 ký tự) → bổ sung email/họ tên → về Dashboard, là Chủ "Tài khoản chính".
7. Cài Tailscale, đăng nhập. Trên trang quản trị Tailscale bật MagicDNS và HTTPS Certificates. Chạy `tailscale serve --bg http://127.0.0.1:8080`, lấy địa chỉ `https://….ts.net` bằng `tailscale serve status`. Sửa `GT_PUBLIC_URL` trong `.env` thành địa chỉ đó, `docker compose up -d`, rồi `docker compose exec keycloak /opt/keycloak/bin/sync-client.sh`. Đăng nhập trên máy tính **và** điện thoại (điện thoại bật Tailscale).
8. Cài MetaTrader 5, đăng nhập tài khoản demo (MetaQuotes-Demo), chuẩn bị chart XAUUSD M15 (theo `mt5_gateway/README.md` Bước 1). Tải repo ZIP, mở `mt5_gateway`, cài `uv`.
9. Trên Dashboard: trang **Tài khoản** → **MT5 Gateway** → **Tạo token Gateway** → sao chép. Dán vào `GT_INGEST_TOKEN` trong `mt5_gateway\gateway.env` (cùng `GT_BROKER_SYMBOL=XAUUSD`, `GT_SERVER_TZ=Europe/Athens`, địa chỉ backend `http://localhost:8080`). Chạy `uv run mt5-gateway check` (đạt 9/9), rồi `uv run mt5-gateway run`. Xác nhận trang Thị trường có nến và sidebar báo MT5 đã kết nối.
10. Diễn tập dừng khẩn cấp: `docker compose stop keycloak` → `docker compose exec backend gt-break-glass halt --all --reason DRILL` → `gt-break-glass status` báo HALTED → `docker compose start keycloak` → đăng nhập lại, thấy HALTED và lịch sử ghi `break-glass`.
11. Diễn tập sao lưu và khôi phục: `docker compose exec backup /usr/local/bin/gt/backup.sh once` → kiểm tra thư mục `C:\gold-trading\backups` → `docker compose stop backend keycloak` → `docker compose run --rm backup restore app latest` → `docker compose run --rm backup restore keycloak latest` → `docker compose up -d` → đăng nhập lại được, dữ liệu còn.

Xong hết thì đối chiếu **Gate GĐ0** trong `CHECKLIST.md`. Cập nhật `PROGRESS.md` và `CHECKLIST.md` (OPS-16, DB-09: đã kiểm chứng trên máy người dùng), commit và push `develop`. Sau đó hỏi người dùng xác nhận đóng GĐ0. Chỉ khi người dùng xác nhận mới chuyển sang GĐ1 và hỏi các quyết định DEC-01..07.

Nếu gặp lỗi: đọc log bằng `docker compose logs --tail 50 <service>`, nhắc người dùng chỉ gửi đoạn log (log đã che bí mật), không gửi `.env`.
