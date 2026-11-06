# Prompt: Hoàn thiện GĐ0 — Nền móng (bảo mật Keycloak, phân quyền, đa tài khoản, log, đồng hồ, sao lưu)

> Dán nguyên phần dưới đường kẻ vào một phiên Claude Code mới trên repo `bmlh3107002/gold_trading`, nhánh `develop`.

---

Bạn tiếp tục dự án **Gold Trading AI**. Nhiệm vụ của phiên này: **hoàn thành toàn bộ Giai đoạn 0 (GĐ0 — Nền móng)** trong `CHECKLIST.md`, gồm đăng nhập bằng **Keycloak**, **phân quyền theo vai trò**, **nền móng đa người dùng** (mỗi người một tài khoản giao dịch riêng), log, kiểm tra đồng hồ, sao lưu và khôi phục. Đây là hệ thống giao dịch bằng tiền thật, nên **đúng và an toàn quan trọng hơn nhanh**.

## 0. Đọc trước khi làm (bắt buộc)

1. `CLAUDE.md`: nguyên tắc thận trọng tài chính và quy ước làm việc.
2. `PROGRESS.md`: trạng thái hiện tại và các lưu ý kỹ thuật.
3. `CHECKLIST.md`: đọc kỹ phần **GĐ0** (danh sách việc, bảng case 0-C01..C18, Gate) và phần **MT** (các việc ghi "GĐ0", case MT-C01..C07).
4. Code liên quan: `backend/src/gold_trading/api/` (app, ingest, market, analysts), `storage/` (schema, repository), `safety/`, `modes/`, `deploy/docker-compose.yml`, `docker-compose.yml`, `frontend/nginx.conf` (nếu có), `frontend/src/api/`, `mt5_gateway/src/mt5_gateway/backend_client.py`.

## 1. Phạm vi (chỉ GĐ0, không làm việc của giai đoạn khác)

| Mã | Việc |
| --- | --- |
| OPS-14 | Keycloak trong docker compose (cả `deploy/docker-compose.yml` lẫn `docker-compose.yml`): phiên bản **ghim cụ thể** (xác minh tag có thật), database riêng, realm + client nhập từ file JSON trong repo (**không chứa bí mật**: client secret, mật khẩu admin lấy từ `.env`), chạy sau reverse proxy cùng origin với dashboard (ví dụ `/auth`), bật brute force detection |
| OPS-07 | Đăng nhập OIDC theo mô hình **BFF**: backend làm Authorization Code + PKCE với client confidential; trình duyệt chỉ giữ cookie phiên `HttpOnly; Secure; SameSite=Strict` (không giữ access token trong JS/localStorage); đăng xuất cả phía Keycloak; mọi API bắt buộc đăng nhập **trừ** `/api/health` và cổng ingest của Gateway; **actor trong audit lấy từ phiên đã xác thực**, bỏ mọi trường actor/approver do client gửi lên |
| OPS-16 | HTTPS khi truy cập từ máy khác qua **Tailscale Serve** (`https://<máy>.<tailnet>.ts.net`); redirect URI/hostname của Keycloak và backend cấu hình qua `.env`; `localhost` dùng cho phát triển. Hướng dẫn thay cho cách `DASHBOARD_BIND=<IP Tailscale>` |
| OPS-17 | **RBAC:** vai trò hệ thống `ADMIN` (realm role trong Keycloak); vai trò theo tài khoản giao dịch `OWNER` / `OPERATOR` / `VIEWER` lưu trong DB ứng dụng, khóa theo `sub` của Keycloak; kiểm quyền ở backend **mỗi request** (thu hồi quyền có hiệu lực ngay). Viết **ma trận quyền** (ai được xem/đổi Safety, Mode, mở khóa LIVE, quản lý người dùng, xoay token Gateway…) ở `docs/thiet-ke/00-xac-thuc-phan-quyen.md` trước khi code |
| OPS-15 | **Lối dừng khẩn cấp khi Keycloak hỏng:** lệnh CLI chạy bằng `docker compose exec backend ...`, **chỉ** cho phép HALT (một tài khoản hoặc toàn hệ thống), không bao giờ cho ACTIVE/LIVE, ghi audit `actor=break-glass` |
| MT-01 | Mô hình `User` (theo `sub`), `TradingAccount` (một tài khoản MT5), bảng thành viên tài khoản + vai trò |
| MT-02 | Thêm `account_id` vào các bảng riêng hiện có (Safety, Mode, audit, analyst output nếu cần) bằng **migration mới** (không sửa migration cũ); dữ liệu hiện có gán cho một tài khoản mặc định; trigger append-only vẫn giữ |
| MT-03 | Mọi API và truy vấn lọc theo tài khoản người dùng có quyền, **chặn ở tầng truy cập dữ liệu**, không chỉ ở giao diện |
| MT-04 | Token Gateway **riêng từng tài khoản**, lưu dạng băm, xoay vòng được (giao diện cho OWNER/ADMIN), token cũ hết hiệu lực ngay; Gateway chỉ ghi được vào tài khoản của token. Giữ tương thích: `GT_INGEST_TOKEN` hiện tại vẫn chạy cho tài khoản mặc định tới khi người dùng xoay token |
| MT-06 | Safety và Mode theo từng tài khoản + kill switch toàn hệ thống (chỉ ADMIN); quy tắc khôi phục khi khởi động (ACTIVE→PAUSED, LIVE→PAPER) áp dụng cho **mọi** tài khoản |
| MT-09 | Dashboard: hiển thị người đang đăng nhập, chọn tài khoản, chỉ thấy tài khoản được cấp quyền; nút bị ẩn/khóa theo quyền (backend vẫn là nơi chặn thật) |
| MT-10 | Quản lý người dùng của tài khoản: thêm theo email/username đã có trên Keycloak, đổi vai trò, gỡ; có audit |
| MT-11 | Bảo vệ bí mật: client secret, token, thông tin MT5 không nằm trong repo, không trả về API, không ghi log |
| OPS-12 | Kiểm tra đồng hồ: so đồng hồ backend với nguồn tin cậy (ví dụ header `Date` của vài máy chủ HTTPS lớn, lấy trung vị); lệch > 2 giây → cảnh báo trên Dashboard; > 30 giây → **ngừng nhận nến realtime** (trả lỗi rõ cho Gateway) cho tới khi hết lệch. Lưu ý: Docker Desktop trên Windows hay bị lệch giờ sau khi máy ngủ |
| OPS-11 | Log JSON có cấu trúc, xoay vòng log (giới hạn dung lượng trong compose), có `correlationId`; **không bao giờ** ghi token, cookie, mật khẩu, client secret (có test quét) |
| DB-09 | Sao lưu tự động DB ứng dụng **và DB Keycloak** (container chạy theo lịch, giữ ≥ 7 bản, ghi ra thư mục trên máy người dùng); script khôi phục; hướng dẫn diễn tập khôi phục trên Windows; cảnh báo khi ổ đĩa > 85% (case 0-C05) |

**Đã xong, không hỏi lại:** GW-05 (người dùng đã đổi token ingest).

**Không làm** trong phiên này: MT-05 (GĐ1), MT-07 (GĐ5), MT-08 (GĐ10), CD (OPS-06, người dùng hoãn), bất kỳ việc nào của GĐ1 trở đi.

## 2. Câu hỏi phải hỏi người dùng TRƯỚC khi code (dùng công cụ hỏi, mỗi câu có lựa chọn đề xuất)

- **DEC-11 / DEC-12**: người dùng khác là ai (người thân/bạn bè hay khách hàng)? Hệ thống có tự giao dịch tiền của họ không? Nhắc rõ rủi ro pháp lý khi quản lý tiền người khác (khuyên hỏi luật sư); không nhận người dùng thứ hai khi chưa trả lời.
- **DEC-13**: hệ thống vẫn chạy trên máy Windows của người dùng (Tailscale) đúng không? Mỗi người dùng khác tự chạy Gateway trên máy của họ?
- Tên miền Tailscale (`<máy>.<tailnet>.ts.net`) của máy chạy Docker, để cấu hình redirect URI.
- Thời gian phiên đăng nhập mong muốn (đề xuất: phiên 8 giờ, không hoạt động 30 phút thì hết).

## 3. Cách làm (bắt buộc)

1. Viết thiết kế `docs/thiet-ke/00-xac-thuc-phan-quyen.md` (luồng đăng nhập, ma trận quyền, mô hình dữ liệu, xử lý khi Keycloak hỏng, lý do chọn BFF) → **gửi người dùng xem tóm tắt trước khi code**.
2. Làm **từng mã việc một** theo thứ tự đề xuất: OPS-14 → OPS-07 → MT-01/02 → OPS-17 → MT-03 → MT-06 → OPS-15 → MT-04 → MT-09/10/11 → OPS-16 → OPS-12 → OPS-11 → DB-09. Mỗi mã: code + test (gồm case xấu) + kịch bản kiểm chứng riêng → đổi trạng thái trong `CHECKLIST.md` → nhật ký `PROGRESS.md` → commit có mã việc → push `develop` → **CI xanh**.
3. **Test không cần Keycloak thật:** giả lập OIDC bằng khóa ký tạo trong test (JWKS cục bộ). Thêm một kịch bản tích hợp chạy Keycloak thật bằng Docker (trong CI job docker hoặc chạy tay) cho luồng đăng nhập đầu-cuối.
4. Phải có test cho mọi case: **0-C01..C18** và **MT-C01..C04, MT-C06**. Đặc biệt:
   - 0-C11: Keycloak tắt → HALT qua CLI vẫn được; Safety không bao giờ tự ACTIVE.
   - 0-C13: thu hồi vai trò → request kế tiếp 403.
   - 0-C14: request từ origin khác / thiếu cookie SameSite → bị chặn.
   - 0-C16: mở khóa LIVE với người duyệt trùng người yêu cầu → từ chối (dựa trên danh tính xác thực).
   - 0-C18: quét log không có token/cookie/mật khẩu.
   - MT-C01..C04: người A không xem/sửa được tài khoản B; Gateway của A không ghi được vào B; HALT của A không ảnh hưởng B; kill switch toàn hệ thống HALT mọi tài khoản.
5. Đổi API → `uv run python scripts/export_openapi.py` (backend) + `npm run gen:api` (frontend). Đổi schema → `storage/schema.py` + migration Alembic mới.
6. Trước mỗi lần push: `uv run pytest -q`, `uv run ruff check .` (backend, và `mt5_gateway/` nếu sửa), `npm run check` + `npm run build` (frontend). Không tắt/bỏ qua test để cho xanh.
7. **Soát lại cuối giai đoạn:** viết kịch bản tấn công/thử lỗi riêng (gọi API không cookie, cookie giả, đổi `account_id`, token Gateway của tài khoản khác, CSRF từ origin khác, Keycloak tắt) và báo cáo trung thực lỗi tìm được + giới hạn còn lại.

## 4. Hướng dẫn người dùng trên máy Windows

Người dùng **không rành kỹ thuật**: giải thích đơn giản bằng tiếng Việt, **mỗi lần chỉ đưa một bước**, đợi người dùng báo kết quả rồi mới sang bước tiếp. Mỗi lệnh PowerShell để trong một khối riêng. Không yêu cầu dán token/mật khẩu vào chat; lệnh in ra phải che bí mật. Các bước cần hướng dẫn:

1. Cập nhật `docker-compose.yml` mới, thêm biến vào `.env` (mật khẩu admin Keycloak, client secret — sinh ngẫu nhiên bằng lệnh, không gõ tay), `docker compose up -d --build`.
2. Bật Tailscale Serve cho HTTPS, đăng nhập trang quản trị Keycloak, tạo tài khoản đăng nhập của người dùng, gán `ADMIN`.
3. Đăng nhập Dashboard trên máy tính và trên điện thoại qua `https://...ts.net`.
4. Xoay token Gateway từ giao diện, cập nhật `gateway.env`, chạy lại `uv run mt5-gateway run`, xác nhận dữ liệu vẫn về.
5. Diễn tập: tắt Keycloak → HALT bằng lệnh CLI → bật lại.
6. Diễn tập khôi phục DB từ bản sao lưu (cả DB Keycloak), kiểm tra dữ liệu và đăng nhập sau khôi phục.

## 5. Kết thúc giai đoạn

- Đối chiếu **Gate GĐ0** trong `CHECKLIST.md` từng dòng; mục nào chưa đạt thì nói rõ.
- Cập nhật `PROGRESS.md` (bảng trạng thái, kết quả test, nhật ký, lưu ý kỹ thuật mới về Keycloak/RBAC), `CHECKLIST.md` (trạng thái từng mã, case), `deploy/README.md`, `mt5_gateway/README.md`.
- Hỏi người dùng xác nhận đóng GĐ0. Chỉ sau khi người dùng xác nhận mới đổi "Giai đoạn hiện tại" sang **GĐ1** và liệt kê các câu hỏi DEC-01..07 của GĐ1.

Trả lời người dùng bằng tiếng Việt. Push lên `develop`, không tạo PR nếu chưa được yêu cầu.
