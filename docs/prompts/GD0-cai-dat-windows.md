# Prompt: Hướng dẫn cài đặt GĐ0 trên máy Windows mới (tiếp tục)

> Dán phần dưới đường kẻ vào một phiên Claude Code mới trên repo `bmlh3107002/gold_trading`, nhánh `develop`.

---

Đọc `CLAUDE.md` và `PROGRESS.md` (đã nạp sẵn); chỉ mở `deploy/README.md` / `mt5_gateway/README.md` khi cần. Code GĐ0 đã xong và CI đã xanh. Việc còn lại để đạt Gate GĐ0 là **hướng dẫn người dùng cài trên máy Windows mới và diễn tập**.

Người dùng không rành kỹ thuật: giải thích đơn giản bằng tiếng Việt, **mỗi lần chỉ đưa một bước**, đợi người dùng báo kết quả rồi mới sang bước tiếp. Mỗi lệnh PowerShell để trong một khối riêng và chỉ dùng ký tự ASCII trong lệnh. Không bao giờ yêu cầu dán mật khẩu, token hay nội dung `.env` vào chat; lệnh kiểm tra chỉ in tên biến hoặc che bí mật.

## Đã làm (máy Windows mới, thư mục `C:\gold-trading`, cập nhật 2026-11-06)

1–6. Docker Desktop, `docker-compose.yml`, `.env` bí mật (+ `GT_MULTI_USER_ENABLED=1`), `docker compose up -d --build`, đăng nhập lần đầu (`admin`, Chủ "Tài khoản chính").
7–11. MT5 (MetaQuotes-Demo, XAUUSD M15), Gateway ở `C:\gold-trading\code\gold_trading-develop\mt5_gateway`, token Gateway, `check` 9/9, `run` có nến.
12–14. Tailscale Serve `https://k.tail8836b4.ts.net`, `GT_PUBLIC_URL` + `sync-client.sh`, đăng nhập máy tính + iPhone. Theme đăng nhập CutlotDesk.
15. Diễn tập break-glass khi tắt Keycloak: đạt (đang HALTED, chưa cần mở lại).
16. MT-20 đạt (tạo `thunghiem`, đăng nhập ẩn danh đúng). Người giao dịch "Lord Trade" đã là Chủ "Tài khoản chính". DEC-15: admin chỉ quản trị, token Gateway ẩn với admin (cần build lại + gỡ admin khỏi "Tài khoản chính").

## Các bước còn lại (mỗi lần một bước)

16. MT-20: `docker compose up -d --build backend frontend keycloak` → đợi healthy → `docker compose exec keycloak /opt/keycloak/bin/sync-client.sh` (dòng cuối kết thúc bằng "quyền tạo người dùng cho backend.") → menu **Quản trị** → tạo thử người dùng → đăng nhập bằng cửa sổ ẩn danh (bị bắt đổi mật khẩu, chỉ thấy tài khoản riêng). Người thân dùng từ máy khác: chia sẻ máy `k` qua Tailscale.
17. Diễn tập sao lưu và khôi phục: `docker compose exec backup /usr/local/bin/gt/backup.sh once` → kiểm tra thư mục `C:\gold-trading\backups` → `docker compose stop backend keycloak` → `docker compose run --rm backup restore app latest` → `docker compose run --rm backup restore keycloak latest` → `docker compose up -d` → đăng nhập lại được, dữ liệu còn.

Xong hết thì đối chiếu **Gate GĐ0** trong `docs/giai-doan/GD0-nen-mong.md`. Cập nhật file đó (OPS-16, DB-09, MT-20: đã kiểm chứng trên máy người dùng + nhật ký) và mục "Trạng thái hiện tại" của `PROGRESS.md`, commit và push `develop`. Sau đó hỏi người dùng xác nhận đóng GĐ0. Chỉ khi người dùng xác nhận mới chuyển sang GĐ1 và hỏi các quyết định DEC-01..07.

Nếu gặp lỗi: đọc log bằng `docker compose logs --tail 50 <service>`, nhắc người dùng chỉ gửi đoạn log (log đã che bí mật), không gửi `.env`.
