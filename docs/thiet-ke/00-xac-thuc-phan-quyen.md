# Thiết kế 00 — Xác thực, phân quyền, đa tài khoản và vận hành nền móng (GĐ0)

> Phạm vi: OPS-07, OPS-11, OPS-12, OPS-14..17, MT-01..04, MT-06, MT-09..11, DB-09 trong `CHECKLIST.md`.
> Trạng thái: **người dùng đã duyệt** (2026-11-06). Sửa file này trước khi đổi hành vi bảo mật.

## 0. Quyết định của người dùng (2026-11-06)

| Mã | Câu trả lời | Hệ quả trong thiết kế |
| --- | --- | --- |
| DEC-11 | Sau này: **người thân/bạn bè**, hệ thống **tự giao dịch** bằng tiền của họ | Nền móng đa tài khoản làm đầy đủ. Tự giao dịch tiền người khác có rủi ro pháp lý (xem DEC-12) |
| DEC-12 | **Chưa trả lời** (cần hỏi luật sư) | `GT_MULTI_USER_ENABLED=0` mặc định: backend **từ chối** thêm người thứ hai vào bất kỳ tài khoản nào. Chỉ bật khi DEC-12 có câu trả lời |
| DEC-13 | Chạy trên **máy Windows của người dùng**; **gom mọi Gateway/MT5 về máy này** | Mỗi tài khoản giao dịch có token Gateway riêng. Nhiều terminal MT5 trên một máy là việc của GĐ1 (MT-05) |
| DEC-15 (2026-11-06) | Tài khoản `admin` **chỉ để quản trị, không giao dịch**; giao dịch bằng người dùng khác là Chủ tài khoản. Mỗi tài khoản giao dịch ↔ một token ↔ một MT5. **Ẩn token Gateway với admin** | ADMIN (không là thành viên) **không** xoay/cấp token Gateway và Dashboard ẩn hẳn mục MT5 Gateway. Lý do: token là chìa khóa nối tài khoản với MT5; admin bị lộ mật khẩu thì không lấy được token để gửi dữ liệu giả hay (sau này) lệnh vào MT5 của người khác. Admin vẫn xem, dừng khẩn cấp, quản lý thành viên; muốn cấp token hộ thì phải tự thêm mình làm Chủ (có audit). Hướng chặt hơn = an toàn hơn |
| DEC-16 (2026-11-06, **thay DEC-15 và ma trận OPS-17**) | Chỉ hai vai trò: **ADMIN** (chỉ quản lý tài khoản USER, không giao dịch) và **USER** (giao dịch trên tài khoản của mình). Token Gateway do hệ thống sinh khi ADMIN tạo USER, **hiện cho ADMIN một lần** để ADMIN cấu hình Gateway trên máy chung. Bỏ kill switch trên Dashboard. Bật LIVE: USER xin, **ADMIN duyệt hoặc từ chối** | Xem **mục 16**. Mục 4 (khởi tạo chủ), 5 (ma trận), 6 (kill switch), 8 (ai cấp token), 15 (chưa có) đã sửa theo |
| Phiên | Tối đa **8 giờ**, không hoạt động **30 phút** thì hết | `GT_SESSION_MAX_HOURS=8`, `GT_SESSION_IDLE_MINUTES=30`; Keycloak cấu hình cùng giá trị |
| Tailscale | Hiện truy cập bằng `http://100.x.y.z:8080` (chưa HTTPS) | Chuyển sang **Tailscale Serve** (HTTPS `*.ts.net`), địa chỉ đặt qua `GT_PUBLIC_URL`; nginx quay về chỉ mở `127.0.0.1` |
| 2 lớp (OTP) | **Chưa bật** | Realm không bắt buộc OTP. Bật sau bằng một thao tác trong Keycloak (Authentication → Required actions → Configure OTP), không cần đổi code |
| Nhánh | Push `develop` như trước; CD để sau | — |

## 1. Kiến trúc

```
Trình duyệt ──HTTPS (Tailscale Serve)──► 127.0.0.1:8080  nginx (container frontend)
                                            ├── /            dashboard (file tĩnh)
                                            ├── /api/        backend (FastAPI, BFF)
                                            └── /auth/       Keycloak
backend ──(mạng nội bộ compose)──► keycloak:8080/auth   (đổi code lấy token, JWKS, làm mới)
backend ──► db (TimescaleDB)          keycloak ──► keycloak-db (Postgres riêng)
backup ──► db + keycloak-db ──► thư mục backups/ trên máy người dùng
MT5 Gateway (Windows) ──HTTP──► 127.0.0.1:8080/api/ingest/... (token Gateway riêng từng tài khoản)
```

- **Cùng origin:** dashboard, API và Keycloak chung một origin (`GT_PUBLIC_URL`). Không cần CORS ở môi trường chạy thật; cookie `SameSite=Strict` dùng được.
- **Không mở cổng mới ra host.** Chỉ nginx mở `127.0.0.1:8080` (hoặc `DASHBOARD_BIND`). Keycloak, các DB và backend chỉ nằm trong mạng nội bộ của compose.
- **Keycloak** chạy `start` (chế độ production), ghim phiên bản **26.8.2** (đã xác minh tag trên Docker Hub ngày 2026-11-06), `KC_HTTP_RELATIVE_PATH=/auth`, `KC_HOSTNAME=${GT_PUBLIC_URL}/auth`, `KC_PROXY_HEADERS=xforwarded`, `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` (backend gọi nội bộ qua `http://keycloak:8080/auth`).
- Image Keycloak được build từ `ops/keycloak/Dockerfile` (thêm file realm vào image), để bản `deploy/` build thẳng từ GitHub vẫn chạy được mà không cần clone.

## 2. Realm và client (OPS-14)

File `ops/keycloak/realm/gold-trading-realm.json` (trong repo, **không chứa bí mật**):

- Realm `gold-trading`; `sslRequired=external`; **brute force detection bật** (khóa tạm sau 5 lần sai, tăng dần, tối đa 15 phút); đăng ký tự do **tắt**; quên mật khẩu tắt (chưa có máy chủ email).
- `ssoSessionIdleTimeout=1800`, `ssoSessionMaxLifespan=28800` (30 phút / 8 giờ). Access token sống 5 phút.
- Realm role `ADMIN`.
- Client `gold-trading-dashboard`: confidential, chỉ bật Standard Flow (Authorization Code), PKCE `S256` bắt buộc, redirect URI chính xác `${GT_PUBLIC_URL}/api/auth/callback`, post-logout redirect `${GT_PUBLIC_URL}/`. Client secret là placeholder `${env.GT_OIDC_CLIENT_SECRET}`: Keycloak đọc từ biến môi trường lúc nhập realm.
- Mapper đưa `realm_access.roles` vào **ID token**, để backend không cần đọc access token.
- Người dùng khởi tạo `${env.GT_ADMIN_USERNAME}` mang role `ADMIN`, mật khẩu tạm lấy từ `.env`, **bắt buộc đổi mật khẩu khi đăng nhập lần đầu**.
- **Lưu ý:** Keycloak chỉ nhập realm khi realm **chưa tồn tại**. Muốn đổi client secret về sau thì đổi trong giao diện quản trị Keycloak **và** trong `.env` (hướng dẫn trong `deploy/README.md`).

Bí mật trong `.env` (sinh ngẫu nhiên bằng lệnh, không gõ tay): `KC_ADMIN_PASSWORD`, `KC_DB_PASSWORD`, `GT_OIDC_CLIENT_SECRET`, `GT_ADMIN_INITIAL_PASSWORD`. Thiếu biến nào thì compose báo lỗi ngay (`${VAR:?...}`), không dùng giá trị mặc định cho bí mật.

## 3. Đăng nhập theo mô hình BFF (OPS-07)

**Lý do chọn BFF** (backend giữ token, trình duyệt chỉ có cookie): token không bao giờ nằm trong JavaScript/localStorage, nên lỗi XSS không lấy được token. Thu hồi phiên làm ở backend, có hiệu lực ngay. Đây là mô hình được khuyến nghị cho ứng dụng trình duyệt (OAuth 2.0 for Browser-Based Apps, IETF).

### 3.1 Luồng

1. `GET /api/auth/login?next=/#market` → backend tạo `state` (32 byte), `nonce`, `code_verifier` (PKCE S256), lưu giao dịch đăng nhập **trong bộ nhớ**, hết hạn sau 10 phút, mỗi `state` dùng **một lần**. Đặt cookie `__Host-gt_login=<state>` (`HttpOnly; Secure; SameSite=Lax; Path=/`, 10 phút) rồi chuyển hướng 302 sang Keycloak.
2. Keycloak xác thực người dùng rồi chuyển về `GET /api/auth/callback?code&state`.
3. Backend kiểm tra: `state` có trong bộ nhớ, chưa dùng, khớp cookie `__Host-gt_login`. Sau đó đổi `code` lấy token ở endpoint nội bộ (gửi client secret và `code_verifier`), rồi **xác minh ID token**: chữ ký RS256 theo JWKS, `iss` = `${GT_PUBLIC_URL}/auth/realms/gold-trading`, `aud` chứa client id, `azp`, `nonce`, `exp`/`iat`/`nbf` với độ lệch cho phép **5 giây** (0-C17). Bất kỳ bước nào sai → 400 kèm trang lỗi, ghi audit `auth.login REJECTED`.
4. Tạo phiên: id ngẫu nhiên 32 byte. Cookie `__Host-gt_session=<id>` (`HttpOnly; Secure; SameSite=Strict; Path=/`). Backend chỉ lưu **băm SHA-256** của id phiên, kèm `sub`, username, email, roles, refresh token, id_token (để đăng xuất), thời điểm tạo và hoạt động gần nhất. Cập nhật bảng `users`, ghi audit `auth.login ACCEPTED`.
5. Chuyển hướng về `next`. Chỉ chấp nhận đường dẫn tương đối bắt đầu bằng `/` và không bắt đầu bằng `//`, để chống open redirect.

**Phiên lưu trong bộ nhớ backend** (không ghi DB). Hệ quả: backend khởi động lại thì mọi người phải đăng nhập lại. Nếu phiên SSO của Keycloak còn hạn, đăng nhập lại chỉ là một lần bấm. Đổi lại, refresh token không bao giờ nằm trong DB hay trong bản sao lưu. Backend chạy **một tiến trình**; muốn chạy nhiều worker thì phải chuyển phiên sang kho dùng chung (ghi ở giới hạn).

### 3.2 Kiểm tra phiên mỗi request

- Không có cookie, phiên không tồn tại, quá 30 phút không hoạt động hoặc quá 8 giờ kể từ khi đăng nhập → **401**. Frontend chuyển sang màn hình "Đăng nhập".
- **Làm mới với Keycloak mỗi 60 giây** (khi có request): dùng refresh token để lấy token mới, cập nhật roles.
  - Keycloak trả `invalid_grant` (người dùng bị vô hiệu hóa, phiên bị thu hồi, đổi mật khẩu) → **hủy phiên, 401** (0-C12).
  - Không kết nối được Keycloak → **giữ phiên tới hết hạn của chính nó** (0-C11), ghi cảnh báo. Cơ chế phiên của backend vẫn giới hạn ở 8 giờ / 30 phút.
- Hệ quả: role `ADMIN` bị gỡ hoặc tài khoản bị vô hiệu hóa trên Keycloak có hiệu lực **trong vòng ≤ 60 giây**. Vai trò theo tài khoản giao dịch lưu ở DB ứng dụng nên có hiệu lực **ngay ở request kế tiếp** (0-C13).

### 3.3 Đăng xuất

`POST /api/auth/logout` → xóa phiên, xóa cookie, trả về URL `end_session` của Keycloak (kèm `id_token_hint`, `post_logout_redirect_uri`). Frontend chuyển trang tới URL đó để kết thúc cả phiên SSO.

### 3.4 Chống CSRF, origin lạ, DNS rebinding (0-C14)

- Cookie phiên `SameSite=Strict`.
- Mọi request **ghi** (POST/PUT/PATCH/DELETE) có cookie phiên phải kèm header `Origin` khớp **chính xác** origin của `GT_PUBLIC_URL` (hoặc `GT_EXTRA_ORIGINS`, mặc định trống; môi trường dev thêm `http://localhost:5173`). Thiếu `Origin` hoặc sai → **403**, ghi audit.
- Kiểm tra `Host` ở middleware: chỉ chấp nhận host của `GT_PUBLIC_URL`, `localhost`, `127.0.0.1`, `backend` (healthcheck nội bộ). Host lạ → 400. Cách này chặn DNS rebinding.
- Body JSON bắt buộc `Content-Type: application/json`, nên form HTML từ trang khác không gửi được.

### 3.5 Endpoint không cần đăng nhập

Chỉ có: `GET /api/health`, `/api/auth/login`, `/api/auth/callback`, `/api/auth/me` (trả 401 nếu chưa đăng nhập), và cổng Gateway `/api/ingest/mt5/*` (xác thực bằng token Gateway). Tất cả endpoint còn lại đều bắt buộc có phiên. Một test duyệt **mọi route** trong OpenAPI để chắc chắn không route nào lọt qua.

### 3.6 Actor trong audit

Bỏ các trường `actor`/`approver` trong body request. Actor = `username` của phiên, kèm `actor_sub` (cột mới trong audit). Gửi thêm trường `actor` sẽ bị từ chối với lỗi 422 (`extra=forbid`), không bị lặng lẽ bỏ qua.

## 4. Mô hình dữ liệu (MT-01, MT-02) — migration `0004`

| Bảng | Loại | Cột chính |
| --- | --- | --- |
| `users` | cập nhật được (hồ sơ) | `sub` (PK), `username`, `email`, `display_name`, `first_login_at`, `last_login_at` |
| `trading_accounts` | thêm mới, không xóa | `account_id` (PK, ví dụ `default`), `name`, `created_at`, `created_by`, `price_feed` (bool: tài khoản này được ghi nến dùng chung) |
| `account_members` | trạng thái hiện tại (thêm/sửa/xóa) | `(account_id, sub)` PK, `role` ∈ OWNER/OPERATOR/VIEWER, `granted_at`, `granted_by`. **Mọi thay đổi đều ghi vào `audit_log`** (append-only) |
| `gateway_tokens` | thêm mới; chỉ được đặt `revoked_at` một lần | `token_id`, `account_id`, `token_sha256` (unique), `created_at`, `created_by`, `revoked_at` |
| `safety_transitions` | append-only | **+ `account_id` NOT NULL** |
| `mode_changes` | append-only | **+ `account_id` NOT NULL** |
| `audit_log` | append-only | **+ `account_id` NULL** (NULL = sự kiện hệ thống), **+ `actor_sub` NULL** |

- Dữ liệu cũ gán cho tài khoản `default` ("Tài khoản chính", `price_feed=true`). Cột mới thêm bằng `ADD COLUMN ... DEFAULT 'default'`. Postgres điền giá trị cho hàng cũ **mà không chạy UPDATE**, nên trigger append-only vẫn giữ nguyên. Sau đó bỏ DEFAULT, để code bắt buộc phải truyền `account_id`.
- `gateway_tokens` có trigger: chỉ cho phép UPDATE đổi `revoked_at` từ NULL sang có giá trị; không cho DELETE.
- Dữ liệu thị trường (`candles`, `analyst_outputs`) **dùng chung**, không thêm `account_id` (theo nguồn/broker là việc MT-05, GĐ1).
- ~~Khởi tạo chủ sở hữu: ADMIN đầu tiên đăng nhập được gán OWNER tài khoản `default`.~~ **Bỏ từ DEC-16:** ADMIN không bao giờ được gán tài khoản giao dịch. Tài khoản `default` (nguồn giá) chưa có chủ → **USER đầu tiên ADMIN tạo** nhận nó (mục 16).
- **Migration `0006` (DEC-16):** `users.role` ∈ ADMIN/USER (mặc định USER, cập nhật từ realm role mỗi lần đăng nhập), `users.status` ∈ ACTIVE/LOCKED (mặc định ACTIVE), `users.updated_at`. Chỉ thêm cột, không xóa/sửa dòng nào; `account_members` giữ nguyên.

## 5. Phân quyền (DEC-16, thay ma trận OPS-17)

Chỉ hai vai trò. **ADMIN** = realm role `ADMIN` trên Keycloak. **USER** = mọi người dùng còn lại. Code: `accounts/access.py` (vài hàm, không còn enum quyền). Kiểm tra ở backend **mỗi request** (đọc DB); giao diện chỉ ẩn nút.

| Hành động | USER (chủ tài khoản, đang ACTIVE) | ADMIN |
| --- | :-: | :-: |
| Xem dữ liệu thị trường, analyst (dùng chung) | ✓ | ✓ (API; giao diện ADMIN không hiện) |
| Xem trạng thái, Safety/Mode, audit, trạng thái Gateway **của tài khoản mình** | ✓ | ✗ |
| PAUSE / HALT / mở lại (thoát HALTED cần tick xác nhận) / đổi Mode BACKTEST·PAPER·SHADOW | ✓ | ✗ |
| Xin bật LIVE | ✓ | ✗ |
| **Duyệt / từ chối** bật LIVE | ✗ | ✓ |
| Danh sách USER, tạo, khóa, mở khóa, đặt lại mật khẩu, cấp lại token Gateway | ✗ | ✓ |
| HALT qua CLI break-glass (OPS-15) | Ai có quyền chạy `docker compose exec` trên máy | |

Quy tắc:
- **"Tài khoản của mình"** = có dòng `account_members` với `role='OWNER'`. Dòng OPERATOR/VIEWER cũ **không cho quyền gì** (bỏ vai trò trung gian không được vô tình mở rộng quyền). ADMIN **không vào được tài khoản giao dịch nào**, kể cả khi còn dòng OWNER cũ.
- Không phải chủ, hoặc là ADMIN → **404** (không lộ tài khoản có tồn tại hay không) + audit `access.denied` (MT-C01). Chủ nhưng bị khóa → **403** + audit (thực tế phiên đã bị thu hồi trước đó → 401).
- Thu hồi quyền sở hữu có hiệu lực ở request kế tiếp (0-C13).
- **Bật LIVE (0-C16):** USER tạo yêu cầu (`POST /api/accounts/{id}/mode/live-requests`, hết hạn sau 15 phút) → ADMIN duyệt (`POST /api/admin/live-requests/{id}/approve`) hoặc từ chối (`.../reject`). Lúc duyệt backend kiểm lại: người xin vẫn là chủ và ACTIVE, người duyệt khác người xin (theo `sub`), rồi mới gọi `ModeManager` (vẫn kiểm `live_unlocked`, `LIVE_CHECKLIST`, chặn dữ liệu SAMPLE). `GT_LIVE_UNLOCKED` vẫn mặc định khóa. Chi tiết theo tài khoản: MT-08 (GĐ10).

## 6. Safety và Mode theo tài khoản (MT-06)

- Mỗi tài khoản có một `SafetySupervisor` và một `ModeManager` riêng. Quy tắc khôi phục khi khởi động (ACTIVE→PAUSED, HALTED giữ, LIVE→PAPER, SAMPLE chặn SHADOW/LIVE) áp dụng cho **từng** tài khoản.
- **DB là nguồn sự thật:** trước mỗi lần đổi trạng thái, backend khóa theo tài khoản (Postgres `pg_advisory_xact_lock`), đọc trạng thái mới nhất trong DB rồi mới ghi. Một vòng nền mỗi **2 giây** đồng bộ trạng thái từ DB. Nhờ vậy lệnh HALT ghi thẳng vào DB bằng CLI (OPS-15) có hiệu lực với backend đang chạy, và backend không thể ghi đè một HALT bằng ACTIVE cũ.
- Đọc DB lỗi → `allows_new_orders()` trả `False` (mặc định an toàn).
- ~~Kill switch toàn hệ thống trên Dashboard~~ **bỏ từ DEC-16** (ADMIN không điều khiển giao dịch). Dừng mọi tài khoản: `gt-break-glass halt --all` (mục 7). Không có lệnh "mở lại toàn bộ": USER mở lại từng tài khoản của mình.
- **USER bị khóa** → `allows_new_orders()` = False cho mọi tài khoản của người đó (Trading Engine), không đổi Safety/Mode, không đóng vị thế.

## 7. Lối dừng khẩn cấp khi Keycloak hỏng (OPS-15)

```
docker compose exec backend gt-break-glass halt --account default --reason KEYCLOAK_DOWN
docker compose exec backend gt-break-glass halt --all --reason KEYCLOAK_DOWN
docker compose exec backend gt-break-glass status
```

- Chỉ có lệnh `halt` và `status`. **Không có** resume, mode hay unlock. Một test kiểm tra mã nguồn CLI không gọi `resume`/`set_mode`.
- Ghi thẳng vào DB, với `actor=break-glass`, `trigger_source=cli`, kèm audit. Không cần Keycloak, không cần backend web đang chạy.
- Ai chạy được `docker compose exec` trên máy chạy Docker thì dùng được lệnh này. Đó là ranh giới tin cậy (máy của người dùng).

## 8. Token Gateway theo tài khoản (MT-04, MT-11)

- Định dạng `gtk_` + 43 ký tự (32 byte ngẫu nhiên). DB chỉ lưu SHA-256. Token có độ ngẫu nhiên cao nên SHA-256 là đủ, không cần bcrypt.
- **DEC-16:** token sinh tự động khi ADMIN tạo USER (cùng transaction với USER + tài khoản) và trả cho ADMIN **đúng một lần**. Cấp lại: `POST /api/admin/users/{sub}/accounts/{account_id}/gateway-token` (chỉ ADMIN, chỉ tài khoản của đúng USER đó): **thu hồi mọi token cũ của tài khoản trong cùng transaction**, trả token mới đúng một lần. USER chỉ xem trạng thái (`GET .../gateway/token`: có token chưa, có ghi nến dùng chung không). Endpoint cũ `POST /api/accounts/{id}/gateway/token` đã bỏ.
- Chủ tài khoản bị khóa → ingest trả **403** cho mọi request mang token của tài khoản đó (cả nhịp tim). Mở khóa → token cũ dùng lại được.
- Ingest: tìm tài khoản theo băm của token. Nếu body có `account_id` khác tài khoản của token → **403** (MT-C02).
- **Cho tới MT-05 (GĐ1)**, chỉ tài khoản có `price_feed=true` (tài khoản `default`) được ghi **nến** vào kho dùng chung. Gateway của tài khoản khác chỉ gửi được nhịp tim. Lý do: broker khác cho giá khác, ghi lẫn sẽ làm hỏng dữ liệu phân tích.
- **Tương thích ngược:** `GT_INGEST_TOKEN` trong `.env` vẫn được chấp nhận cho tài khoản `default`, cho tới khi tài khoản này có token đầu tiên trong DB. Sau đó token cũ bị từ chối dù vẫn còn trong `.env`.
- Trạng thái Gateway (`GatewayMonitor`) tách theo tài khoản.
- Bí mật (client secret, token, mật khẩu, cookie) không có trong repo, không bao giờ trả về API (trừ token mới đúng một lần), không ghi log (OPS-11). **Mật khẩu MT5** chỉ nằm trong terminal MT5 trên máy Windows; backend không bao giờ nhận hay lưu mật khẩu MT5. (Số login + server MT5 không phải bí mật và **sẽ** được lưu làm liên kết — mục 14.)
- **Giới hạn quan trọng:** token Gateway chỉ chứng minh "chương trình đang gửi có token của tài khoản giao dịch X". Nó **không** chứng minh terminal đang đăng nhập đúng MT5 nào. Việc liên kết và xác minh danh tính MT5 là mục 14, **chưa làm trong GĐ0**.

## 9. Kiểm tra đồng hồ (OPS-12, 0-C09, 0-C17)

- Vòng nền chạy mỗi 5 phút (1 phút nếu đang lệch): gửi `HEAD` tới 5 máy chủ HTTPS lớn (`www.google.com`, `www.cloudflare.com`, `www.microsoft.com`, `www.apple.com`, `www.amazon.com`). Độ lệch = header `Date` − điểm giữa thời gian gửi/nhận. Lấy **trung vị**, cần ít nhất **3** kết quả hợp lệ.
- Header `Date` chỉ chính xác tới 1 giây, nên phép đo có sai số khoảng ±1 giây. Ngưỡng 2 giây vì vậy chỉ dùng để **cảnh báo**.
- |lệch| ≤ 2 s → `OK`. 2–30 s → `WARN` (banner trên Dashboard). > 30 s → `BLOCKED`: cổng ingest trả **503** kèm hướng dẫn ("đồng hồ máy chủ lệch Xs; khởi động lại Docker Desktop hoặc đồng bộ giờ Windows") cho tới khi hết lệch. Nhịp tim Gateway vẫn được nhận để Dashboard hiển thị trạng thái.
- Không đo được (mất mạng ra ngoài) → `UNKNOWN`: có cảnh báo trên Dashboard nhưng **không chặn** ingest. Lý do: khi không biết thì không nói được đồng hồ sai, và chặn ingest không bảo vệ được tiền mà chỉ làm mất dữ liệu. Phân tích vẫn chỉ dùng nến đã đóng. Nếu người dùng muốn chặt hơn, có thể đổi bằng `GT_CLOCK_UNKNOWN_BLOCKS=1`.
- Docker Desktop trên Windows hay lệch giờ sau khi máy ngủ. Cách sửa (ghi trong README): khởi động lại Docker Desktop.

## 10. Log (OPS-11, 0-C18)

- Log JSON một dòng: `ts`, `level`, `logger`, `msg`, `correlation_id`, các trường thêm. nginx tạo `X-Request-ID` và chuyển cho backend; backend trả lại header này trong response.
- **Bộ lọc che bí mật** áp dụng cho mọi log (gồm uvicorn access log): `Bearer ...`, `gtk_...`, giá trị cookie, `code=`, `state=`, `password`, `client_secret`, `refresh_token`, `id_token`, JWT (`eyJ...`). nginx dùng định dạng log riêng, ghi `$uri` (không có query string) và không ghi header.
- Compose giới hạn log: `json-file`, `max-size: 10m`, `max-file: 5` cho mọi service.
- Test 0-C18: chạy luồng đầy đủ (đăng nhập, callback, ingest có token, xoay token, đăng xuất) với log ở mức DEBUG, rồi quét toàn bộ log tìm các bí mật đã dùng.

## 11. Sao lưu và khôi phục (DB-09, 0-C04, 0-C05)

- Service `backup` (image build từ `ops/backup`, nền `timescale/timescaledb:2.17.2-pg16` để `pg_dump`/`pg_restore` cùng phiên bản với server). Mỗi 24 giờ (`GT_BACKUP_INTERVAL_HOURS`), và chạy ngay khi khởi động nếu bản gần nhất đã cũ hơn khoảng đó:
  - `pg_dump -Fc` DB ứng dụng và DB Keycloak → file tạm, kiểm tra bằng `pg_restore --list`, tính SHA-256, rồi đổi tên thành file chính thức (bản dở dang không bao giờ mang tên hợp lệ).
  - Giữ **14** bản gần nhất mỗi DB (≥ 7 theo yêu cầu). Ghi `status.json` (thời điểm, kích thước, kết quả, % dung lượng ổ).
  - Ghi vào `${GT_BACKUP_DIR:-./backups}` trên máy người dùng (bind mount).
- Backend đọc `status.json` (mount chỉ đọc) và hiển thị trên Dashboard: bản sao lưu gần nhất, cảnh báo nếu cũ hơn 26 giờ hoặc lần chạy gần nhất lỗi.
- **Dung lượng đĩa (0-C05):** backend đo ổ chứa dữ liệu Docker và ổ chứa bản sao lưu. Trên 85% → cảnh báo trên Dashboard và trong log. Khi DB không ghi được (ổ đầy), ingest trả **503** kèm thông báo rõ; transaction bị hủy nên dữ liệu đã ghi không mất.
- **Khôi phục:** `docker compose run --rm backup restore app <file>` / `restore keycloak <file>`. Script chỉ chạy khi `backend`/`keycloak` đã dừng; kiểm tra SHA-256; tạo lại DB; với TimescaleDB thì gọi `timescaledb_pre_restore()` → `pg_restore` → `timescaledb_post_restore()`. Sau khôi phục, backend khởi động theo quy tắc ACTIVE→PAUSED, nên Safety **không bao giờ** tự ACTIVE (0-C04).
- Hướng dẫn diễn tập trên Windows trong `deploy/README.md`.

## 12. Kiểm thử

- **Không cần Keycloak thật:** test sinh khóa RSA, tự dựng JWKS và token endpoint giả qua `httpx.MockTransport`, rồi chạy luồng login → callback → API. Có case xấu: chữ ký sai, `iss`/`aud`/`nonce` sai, token hết hạn, lệch đồng hồ quá 5 giây, `state` dùng lại, thiếu cookie đăng nhập, `invalid_grant` khi làm mới, Keycloak không truy cập được.
- **Tích hợp với Keycloak thật:** `ops/scripts/e2e_auth.py` dựng compose (Keycloak + backend + nginx), đăng nhập qua form Keycloak, gọi API, đăng xuất. Chạy trong job `docker` của CI.
- Case bắt buộc có test: 0-C01..C18, MT-C01..C04, MT-C06 (bảng ánh xạ test ↔ case sẽ ghi trong `CHECKLIST.md`).

## 13. Giới hạn đã biết

- Phiên lưu trong bộ nhớ, backend chạy một tiến trình. Khởi động lại backend thì phải đăng nhập lại.
- Gỡ `ADMIN` hoặc vô hiệu hóa người dùng trên Keycloak có hiệu lực trong ≤ 60 giây (vai trò theo tài khoản có hiệu lực ngay).
- Thêm thành viên chỉ theo username/email của người **đã đăng nhập ít nhất một lần** (backend không cần quyền đọc danh sách người dùng của Keycloak, nên ít quyền hơn).
- HALT bằng CLI cần DB còn chạy. DB chết thì không ghi được trạng thái nào (hiện chưa có lệnh thật; Guardian EA ở GĐ9 sẽ là lớp bảo vệ độc lập).
- Trang quản trị Keycloak (`/auth/admin`) truy cập được trong tailnet, được bảo vệ bằng mật khẩu mạnh và brute force detection.

## 14. Luồng người dùng → liên kết MT5 → giao dịch đúng MT5 (yêu cầu chính thức, người dùng chốt 2026-11-06)

### 14.1 Yêu cầu

1. Người dùng đăng nhập website bằng tài khoản riêng (Keycloak).
2. Trong trang cấu hình, người dùng **liên kết** tài khoản website với tài khoản MT5 của mình thông qua Gateway chạy trên Windows.
3. Gateway kết nối **đúng terminal MT5 đã cấu hình** và đọc danh tính tài khoản đang đăng nhập trong terminal. Backend lưu liên kết gồm **MT5 login, broker/server và Gateway**. Không chỉ dựa vào tên hiển thị hay token.
4. Khi hệ thống tạo lệnh cho người dùng đó, backend gửi yêu cầu tới **đúng Gateway đã liên kết**. Thành phần thực thi tại Gateway đặt lệnh bằng tài khoản đang đăng nhập trên terminal tương ứng.
5. Lệnh, vị thế, vốn, hạn mức rủi ro, Safety, Mode và lịch sử **tách riêng theo tài khoản**. Thiếu liên kết thì **không bao giờ** tự dùng MT5 chính hay Gateway của người khác.
6. **Trước mỗi lần đặt/sửa/hủy/đóng lệnh**, thành phần thực thi kiểm tra tài khoản thực tế trong terminal có khớp `MT5 login + server` đã liên kết hay không. Người dùng đổi tài khoản trên terminal, mất kết nối hoặc liên kết sai → **chặn thao tác, cảnh báo, yêu cầu xác minh lại**. Không âm thầm chuyển sang tài khoản mới.

Ví dụ: website A liên kết MT5 `111111` trên server `Broker X` → mọi lệnh của A chỉ vào MT5 đó. Website B liên kết `222222` trên `Broker Y` → mọi lệnh của B chỉ vào MT5 đó.

**Giao diện giai đoạn đầu:** mỗi người một MT5 mặc định. Đăng nhập xong tự dùng liên kết của mình. Bên trong vẫn giữ `TradingAccount` để tổ chức dữ liệu và phân quyền, nhưng người chỉ có một tài khoản giao dịch thì **không** phải chọn tài khoản (bộ chọn chỉ hiện khi có từ 2 tài khoản trở lên — MT-19, làm trong GĐ0).

### 14.2 Đã có (GĐ0) và còn thiếu

| Phần | Trạng thái | Ghi chú |
| --- | --- | --- |
| Đăng nhập riêng từng người, phân quyền theo tài khoản giao dịch | Có (GĐ0) | OPS-07, OPS-17, MT-01..03 |
| Safety, Mode, audit riêng từng tài khoản | Có (GĐ0) | MT-02, MT-06 |
| Token Gateway riêng từng tài khoản; Gateway khai sai `account_id` → 403 | Có (GĐ0) | MT-04. **Không phải** xác minh danh tính MT5 |
| Tài khoản không phải nguồn giá thì không ghi được nến dùng chung | Có (GĐ0) | Không có đường nào để một tài khoản dùng dữ liệu/MT5 của tài khoản khác |
| Gateway đọc MT5 login + server + company + loại tài khoản của terminal | Có (GĐ1, 2026-11-07) | MT-12: trường `identity` trong nhịp tim, đọc trực tiếp mỗi lần. Chỉ báo; chưa dùng để liên kết/chặn (MT-13/MT-14) |
| Gateway kết nối đúng terminal đã cấu hình (nhiều terminal trên một máy) | **Thiếu** | → MT-15 (GĐ1) |
| Bảng liên kết + luồng xác minh có người xác nhận | Có (GĐ1, code 2026-11-07) | MT-13: bảng `mt5_links` (migration 0008), mục 14.5. Chờ kiểm trên máy người dùng |
| Phát hiện terminal đổi tài khoản / sai liên kết → chặn + cảnh báo | **Thiếu** | → MT-14 (GĐ1) |
| Lệnh, vị thế, vốn, hạn mức, ledger theo tài khoản | **Thiếu** | → MT-07 (GĐ5), MT-16 (GĐ8) |
| Định tuyến lệnh tới đúng Gateway đã liên kết | **Thiếu** | → MT-17 (GĐ9) |
| Kiểm tra login + server ngay trước mọi thao tác lệnh | **Thiếu** | → MT-18 (GĐ9) |

**Luồng giao dịch riêng từng người chưa hoàn thành.** Không được đánh dấu xong chỉ vì đã có token Gateway theo tài khoản.

### 14.3 Thiết kế dự kiến (làm ở giai đoạn ghi bên cạnh, sẽ có thiết kế chi tiết riêng)

**Danh tính MT5** = `(login, server)`. `company` dùng để hiển thị và đối chiếu thêm. Không dùng tên hiển thị, tên terminal hay token làm danh tính.

**Liên kết** (bảng `mt5_links`, chỉ thêm và đổi trạng thái, có audit) gồm: `account_id`, `mt5_login`, `mt5_server`, `mt5_company`, `gateway_id`, `token_id`, `trade_mode` (DEMO/REAL), `status`, `verified_at`, `verified_by`. Mỗi tài khoản giao dịch có tối đa **một** liên kết ACTIVE.

**Trạng thái liên kết:**

```
UNLINKED ──Gateway báo danh tính──► PENDING_CONFIRM ──OWNER xác nhận "login 111111 / Broker X"──► ACTIVE
ACTIVE ──danh tính terminal khác liên kết──► MISMATCH   (chặn ghi + chặn lệnh, cảnh báo; KHÔNG tự đổi)
ACTIVE ──mất nhịp tim / terminal đăng xuất──► DISCONNECTED (chặn lệnh mới; tự về ACTIVE chỉ khi danh tính ĐÚNG như cũ)
MISMATCH ──OWNER xác minh lại (chọn: quay về MT5 cũ, hoặc liên kết MT5 mới = liên kết mới)──► ACTIVE
ACTIVE ──OWNER gỡ──► REVOKED
```

- Liên kết MT5 mới luôn tạo **liên kết mới**, cần xác nhận lại. Lịch sử lệnh/vị thế cũ vẫn thuộc liên kết cũ, không trộn.
- Cùng một `(login, server)` không được ACTIVE ở hai tài khoản giao dịch khác nhau.
- Tài khoản REAL: xác nhận liên kết cần thêm bước cảnh báo rõ. Mode vẫn theo quy tắc LIVE hai người (MT-08, GĐ10).

**Thực thi (GĐ9):**
- Thành phần thực thi là **package riêng** (GW-10), tách khỏi `mt5_gateway` (vẫn chỉ đọc). Hai thành phần có thể chạy trên cùng máy Windows, cùng terminal.
- Backend chỉ giao lệnh của tài khoản X cho thành phần thực thi đã xác thực bằng thông tin của **liên kết ACTIVE của X**. Không có liên kết ACTIVE thì không giao lệnh và không có đường dự phòng.
- Mỗi lệnh mang `expected_login`, `expected_server`, `link_id`. Ngay trước `order_send` / sửa / hủy / đóng, thành phần thực thi gọi `account_info()` + `terminal_info()`: không khớp, không kết nối, hoặc không đọc được thì **từ chối** với mã lý do `MT5_IDENTITY_MISMATCH` / `MT5_DISCONNECTED`. Backend chuyển liên kết sang MISMATCH/DISCONNECTED, PAUSE/HALT tài khoản đó (chỉ tài khoản đó), ghi audit và cảnh báo.
- Thao tác bảo vệ (đóng/hạn chế vị thế) khi đổi tài khoản cũng phải nhắm đúng MT5 đã liên kết. Nếu terminal đang đăng nhập MT5 khác thì không thao tác trên MT5 khác đó. Guardian EA trên MT5 cũ là lớp bảo vệ.

### 14.4 Bất biến (áp dụng từ bây giờ cho mọi code mới)

- Không code nào được chọn MT5/Gateway "mặc định" cho một tài khoản không có liên kết của chính nó.
- Danh tính MT5 so khớp theo `(login, server)` do terminal báo, không theo dữ liệu người dùng gõ tay.
- Mọi bảng lệnh/vị thế/ledger/vốn/hạn mức mới đều có `account_id` (và `link_id` khi liên quan MT5), lọc ở tầng truy cập dữ liệu như MT-03.

### 14.5 MT-13 đã làm (2026-11-07)

- **Bảng `mt5_links`** (migration 0008): mỗi liên kết một dòng, chỉ đổi cột trạng thái/xác minh/kết thúc; Postgres có trigger chặn DELETE; mọi lần đổi trạng thái có audit (`mt5_link.pending` / `mt5_link.confirm` / `mt5_link.revoke`). Trạng thái: `PENDING_CONFIRM`, `ACTIVE`, `MISMATCH`, `DISCONNECTED` (hai trạng thái này dành cho MT-14), `REVOKED`, `CANCELLED`. "Đang giữ" = ACTIVE/MISMATCH/DISCONNECTED.
- **Index duy nhất có điều kiện ở DB** (lớp phòng thủ cuối, kể cả khi hai tài khoản xác nhận cùng lúc): `(login, lower(server))` chỉ được giữ ở một tài khoản (MT-C11); mỗi tài khoản giữ tối đa một liên kết; mỗi tài khoản tối đa một liên kết chờ.
- **Tạo liên kết chờ** (`accounts/mt5_link.py::observe_identity`, gọi sau mỗi nhịp tim đã xác thực): chỉ cho **tài khoản của token**; không có `identity`, loại tài khoản `UNKNOWN`, hoặc tên server có khoảng trắng đầu/cuối / ký tự điều khiển / ký tự vô hình → **không tạo** (tìm được khi soát: `" Broker-Demo"` hay `"broker-demo"` có thể bị coi là MT5 khác để lách MT-C11 → sửa bằng chặn tên lạ + so server không phân biệt hoa/thường). Terminal đổi MT5 trước khi xác nhận → liên kết chờ cũ `CANCELLED` (`REPLACED`), tạo liên kết chờ mới. Đã có liên kết đang giữ → **không làm gì** (MT-14 sẽ chuyển MISMATCH + chặn). Lỗi DB lúc tạo → bỏ qua (không liên kết = an toàn), nhịp tim vẫn nhận. Lưu `gateway_id` + `token_id` (NULL = token cũ `GT_INGEST_TOKEN`).
- **Xác nhận** (`POST /api/accounts/{id}/mt5-link/confirm`, chỉ chủ tài khoản đang ACTIVE): USER **gõ lại số login** (server do giao diện gửi lại). Backend chỉ nhận khi (1) liên kết còn chờ, (2) login + server gõ/gửi trùng đúng danh tính terminal đã báo, (3) nhịp tim **còn hạn** (≤ 30 s) **vẫn** báo đúng `(login, server, loại tài khoản)` đó, (4) REAL thì phải có `acknowledge_real=true`, (5) MT5 chưa được giữ ở tài khoản khác (thông báo không lộ tài khoản kia). Trường lạ → 422. Dữ liệu gõ tay chỉ để xác nhận, không bao giờ thay danh tính terminal báo.
- **Gỡ** (`POST .../mt5-link/revoke`): liên kết đang giữ → `REVOKED`; liên kết chờ → `CANCELLED` ("Không phải MT5 của tôi"). Đang LIVE → từ chối (chuyển khỏi LIVE trước). Liên kết lại = dòng mới, phải xác nhận lại (MT-C14). ADMIN xóa USER → liên kết của USER đó kết thúc (`USER_DELETED`) để MT5 không bị giữ chỗ mãi.
- **Chưa làm (MT-14):** phát hiện terminal đổi MT5 / đăng xuất khi đang ACTIVE → MISMATCH/DISCONNECTED + chặn ghi + cảnh báo. Liên kết chưa được dùng để cho phép/chặn ghi nến (MT-05).
- **Giới hạn:** số login > 2^53 hiển thị/gõ trên trình duyệt có thể sai số (JavaScript) → backend từ chối vì không khớp (an toàn; login MT5 thực tế nhỏ hơn nhiều). Hai terminal luân phiên dùng cùng một token (cấu hình sai) sẽ tạo/hủy liên kết chờ liên tục — MT-15 xử lý (mỗi terminal một token).

## 15. ADMIN tạo người dùng trên Dashboard (MT-20, người dùng chốt 2026-11-06)

**Yêu cầu:** tạo người dùng ngay trên Dashboard (menu **Quản trị**, chỉ ADMIN thấy), tự tạo bên Keycloak; mỗi người mới có **tài khoản giao dịch riêng** và là **Chủ**; ADMIN tự nhập mật khẩu tạm; **không giới hạn số người** (khi `GT_MULTI_USER_ENABLED=1`, DEC-12).

**Luồng** (`POST /api/admin/users`, `api/users.py`):
1. Chỉ ADMIN (realm role); người khác → 403 + audit, không gọi Keycloak. `GT_MULTI_USER_ENABLED=0` → 409.
2. Kiểm dữ liệu: username `^[a-z0-9][a-z0-9._-]{2,29}$`, email, họ, tên, mật khẩu ≥ 12 ký tự và khác username/email. Mã tài khoản `u-<username>` (`.` → `-`).
3. Keycloak Admin API (`auth/kc_admin.py`): token `client_credentials` của chính client `gold-trading-dashboard` với scope **tùy chọn** `kc-admin-api` (Keycloak ≥ 26.8 bắt buộc audience này; token đăng nhập của người dùng không có). Tạo người dùng `enabled`, `emailVerified`, mật khẩu **temporary** → Keycloak bắt đổi ở lần đăng nhập đầu; chính sách mật khẩu realm do Keycloak kiểm (đã thử thật: ngắn, trùng username → 400).
4. Một giao dịch DB (`provision_user`): hồ sơ `users` (`first_login_at` NULL = chưa đăng nhập, migration 0005) + `trading_accounts` (`price_feed=false`) + `account_members` OWNER. Lỗi DB → **xóa người dùng vừa tạo trên Keycloak** (không để đăng nhập mồ côi), audit REJECTED.
5. Audit `user.create` không bao giờ chứa mật khẩu. Lỗi 422 toàn hệ thống **không trả lại giá trị đã gửi** (trước đây FastAPI trả nguyên `input`, có thể lộ mật khẩu — tìm được khi viết test).

**Quyền của service account** (`realm-management`): chỉ `manage-users` + `view-users` (CI `check_realm.py` kiểm). Đã thử thật: không sửa được cài đặt realm (403), không đọc được realm `master` (403). Rủi ro còn lại: `manage-users` về lý thuyết cho phép gán realm role; backend không có code làm việc đó, và bí mật client đã là bí mật cấp cao nhất của backend.

**Cài đặt đã có từ trước:** realm chỉ nhập một lần → chạy `sync-client.sh` (bật service account, cấp hai quyền trên, thêm scope `kc-admin-api` tùy chọn). Thiếu bước này → API trả 503 kèm hướng dẫn.

**Kiểm thử:** `tests/test_admin_users.py` (20 test: quyền, DEC-12, trùng, dữ liệu sai, Keycloak hỏng/chưa cấp quyền, bù trừ khi DB lỗi, SQL, không giới hạn số người, không lộ mật khẩu); Keycloak 26.8.2 thật (realm cũ + `sync-client.sh`, cài mới); `ops/scripts/ci_stack.sh` (ADMIN tạo → người mới đăng nhập, bị bắt đổi mật khẩu, chỉ thấy tài khoản riêng, không vào được Tài khoản chính, không tạo được người dùng; mật khẩu không có trong log). Frontend: `AdminPage.test.tsx`.

**Cập nhật DEC-16:** đã có danh sách / khóa / mở khóa / đặt lại mật khẩu / cấp lại token (mục 16). Mật khẩu tạm bỏ trống → hệ thống tự sinh. **Còn chưa có:** xóa người dùng (làm trên trang quản trị Keycloak); tài khoản giao dịch mới chưa ghi nến dùng chung và chưa liên kết MT5 (MT-05, MT-12..15, GĐ1).

## 16. Đơn giản hóa phân quyền: chỉ ADMIN và USER (DEC-16, người dùng chốt 2026-11-06)

**Yêu cầu:** chỉ hai vai trò; ADMIN chỉ quản lý tài khoản (xem danh sách, tạo, khóa, mở khóa, đặt lại mật khẩu), không giao dịch; USER giao dịch trên tài khoản của mình bằng token Gateway riêng; bỏ OWNER/OPERATOR/VIEWER, ma trận quyền, kill switch trên Dashboard. Người dùng chọn thêm: token **hiện cho ADMIN** lúc tạo (ADMIN tự cấu hình Gateway trên máy chung); **bỏ** nút dừng khẩn cấp của ADMIN; bật LIVE phải được **ADMIN đồng ý**.

**Giữ, không tự viết lại:** Keycloak lưu mật khẩu (băm theo chính sách của Keycloak 26), khóa đăng nhập (`enabled=false`), thu hồi phiên SSO (`/users/{id}/logout`), mật khẩu tạm (`temporary=true`). Đăng nhập vẫn qua `/api/auth/login` → Keycloak (BFF). Kiến trúc Gateway (đọc token từ `gateway.env`) giữ nguyên: backend **không** đẩy token vào máy Windows được, nên "đăng ký Gateway" = token đã lưu (băm) và gắn đúng tài khoản ở backend; trạng thái `WAITING` cho tới nhịp tim đầu tiên → `CONNECTED`.

**API quản trị** (`api/users.py`, chỉ ADMIN; người khác 403 + audit; không thao tác lên chính mình hay lên ADMIN → 404):

| Endpoint | Làm gì |
| --- | --- |
| `GET /api/admin/users` | USER: trạng thái, lần đăng nhập, tài khoản + trạng thái Gateway (`NO_TOKEN`/`WAITING`/`CONNECTED`/`DISCONNECTED`/`BLOCKED`). Không có token, mật khẩu |
| `POST /api/admin/users` | Keycloak → một transaction DB: USER (ACTIVE) + tài khoản + OWNER + token. Lỗi DB → xóa người dùng trên Keycloak, báo lỗi (gọi lại an toàn, không có USER thiếu token hay token mồ côi). Trả token (và mật khẩu tạm nếu tự sinh) **một lần**, `Cache-Control: no-store` |
| `POST /api/admin/users/{sub}/lock` | **DB trước** (backend chặn ngay: phiên bị thu hồi ở request kế tiếp, đăng nhập mới bị chặn ở callback, Gateway 403, không lệnh mới) → xóa phiên backend → Keycloak `enabled=false` + logout. Keycloak lỗi → khóa **vẫn có hiệu lực**, trả `keycloak_synced=false` để bấm lại (idempotent). Không đóng vị thế, không đổi Safety/Mode |
| `POST /api/admin/users/{sub}/unlock` | Keycloak `enabled=true` **trước**, DB sau (Keycloak lỗi → vẫn khóa, 503). Không tự bật bot |
| `POST /api/admin/users/{sub}/reset-password` | Mật khẩu tạm ngẫu nhiên (≥ 120 bit) → Keycloak `temporary=true` → logout + xóa phiên. Token Gateway giữ nguyên |
| `POST /api/admin/users/{sub}/accounts/{account_id}/gateway-token` | Cấp lại token (làm mất / nghi lộ); token cũ chết ngay |
| `GET /api/admin/live-requests`, `POST .../{id}/approve`, `POST .../{id}/reject` | Duyệt / từ chối bật LIVE |

**USER đầu tiên nhận tài khoản nguồn giá:** khi `default` chưa có chủ (mới cài), USER đầu tiên ADMIN tạo nhận `default` (để Gateway của họ ghi được nến dùng chung); USER sau nhận `u-<username>` (`price_feed=false`). Kiểm "chưa có chủ" trong cùng transaction.

**Khóa có hiệu lực ở đâu (không chỉ giao diện):** `AuthService.authenticate` (mọi request: đọc `users.status`, LOCKED → thu hồi phiên, 401), callback đăng nhập (`auth_error=locked`), `Guard.check` (403), ingest (`account_locked` → 403), `AccountRegistry.allows_new_orders` (False). Đọc DB lỗi → ném lỗi / False (chặn).

**Dữ liệu hiện có (máy người dùng):** migration 0006 chỉ thêm cột. Dòng của ADMIN ghi `USER` tới lần đăng nhập kế tiếp (backend khởi động lại thì mọi phiên mất → ADMIN phải đăng nhập lại → cột cập nhật); trong lúc đó backend vẫn chặn ADMIN thao tác lên chính mình. Dòng OWNER cũ của ADMIN (nếu còn) bị bỏ qua.

**Đánh đổi đã chấp nhận:** ADMIN thấy token của USER (một lần) và đặt lại được mật khẩu USER (thấy mật khẩu tạm) → về lý thuyết ADMIN có thể đăng nhập thay USER. Đây là hệ quả của "ADMIN cấu hình máy chung" mà người dùng chọn; mọi thao tác đều có audit. Muốn tách hẳn: chuyển sang hiện token cho USER (một lựa chọn đã đưa ra, người dùng chưa chọn).

**Kiểm thử:** `tests/test_rbac.py` (ADMIN không vào tài khoản giao dịch kể cả có dòng OWNER cũ; dòng OPERATOR/VIEWER không cho quyền; cách ly; khóa thu hồi phiên + chặn đăng nhập + chặn lệnh mới; duyệt/từ chối LIVE), `tests/test_admin_users.py` (tạo + token + mật khẩu tự sinh, danh sách không lộ bí mật, khóa/mở khóa khi Keycloak lỗi, đặt lại mật khẩu giữ token, không tự khóa mình), `tests/test_gateway_tokens.py` (USER bị khóa → Gateway 403, mở khóa dùng lại token), migration 0006 thử trên PostgreSQL 16 thật (không mất dòng, CHECK chặn giá trị sai). Frontend: `AdminPage.test.tsx`, `AccountPage.test.tsx`, `App.test.tsx`. E2E với Keycloak thật: `ops/scripts/e2e_auth.py` (chạy trong CI).


## 17. Trang Quản trị đơn giản: một USER một dòng, USER xin token, ADMIN cấp (DEC-17, người dùng chốt 2026-11-07)

**Yêu cầu (người dùng):** trang Quản trị chỉ hiện **người dùng**, không tách bảng "tài khoản giao dịch" (dòng "Tài khoản chính · Nguồn giá chung · default" gây hiểu nhầm). ADMIN có: **thêm, sửa, xóa, khóa** (+ mở khóa, đặt lại mật khẩu đã có). Tạo người dùng **không** sinh token; USER muốn dùng MT5 thì **xin cấp token**, ADMIN **cấp**. Người dùng chọn **lựa chọn B**: token **hiện cho ADMIN** (một lần) vì ADMIN cấu hình Gateway trên máy chung (DEC-13); USER không bao giờ thấy token. Thay phần "token sinh lúc tạo" của mục 15/16.

**Mô hình:** mỗi USER đúng một tài khoản giao dịch (ẩn với ADMIN). "Tài khoản chính" của USER = tài khoản cấp giá nếu có, nếu không thì tài khoản tạo sớm nhất. Mã tài khoản mới: `u-<username>`, trùng (tên đăng nhập dùng lại sau khi xóa) → `u-<username>-2`… (tài khoản cũ giữ để còn lịch sử, không bao giờ trao lại cho người mới).

**API (thay đổi so với mục 16):**

| Endpoint | Làm gì |
| --- | --- |
| `GET /api/admin/users` | Một dòng/USER: trạng thái, Gateway (`NO_TOKEN` = chưa có token **còn hiệu lực**), `token_requested_at` (đang xin), `price_feed` (MT5 của người này cấp giá cho cả hệ thống). Không có mã tài khoản, token, mật khẩu. Ẩn USER `DELETED` |
| `POST /api/admin/users` | Như cũ nhưng **không** sinh token (token cũ của tài khoản nhận lại vẫn bị thu hồi). Bỏ trường `account_name` |
| `PUT /api/admin/users/{sub}` | Sửa email / họ / tên (tên đăng nhập không đổi). Kiểm email trùng ở DB, rồi Keycloak: **đọc bản đầy đủ rồi gửi lại cả bản** (Keycloak ≥ 24 có thể xóa thuộc tính không gửi kèm). Keycloak lỗi → 503, DB không đổi |
| `DELETE /api/admin/users/{sub}` | **Từ chối (409)** nếu tài khoản của USER đang cấp giá, đang LIVE, hoặc Gateway đang kết nối. Xóa = DB `status=DELETED` **trước** (chặn ngay: phiên, đăng nhập, Gateway, lệnh mới) → thu hồi mọi token → hủy yêu cầu xin token → thu hồi phiên → xóa trên Keycloak. Keycloak lỗi → `keycloak_synced=false`, bấm lại (cho phép gọi lại trên USER đã `DELETED`). Giữ dòng `users` + lịch sử |
| `POST /api/admin/users/{sub}/gateway-token` | Cấp token cho tài khoản của USER (thu hồi token cũ trong cùng transaction), đánh dấu yêu cầu đang chờ là `APPROVED`. Dùng cả khi không có yêu cầu (cấp lại khi mất). USER đang khóa → 409 |
| `POST /api/admin/users/{sub}/gateway-token/reject` | Từ chối yêu cầu đang chờ (204); không có yêu cầu → 409. Token đang dùng không đổi |
| `POST /api/accounts/{id}/gateway/token-request` | USER (chủ, ACTIVE) xin cấp/cấp lại token. Đang chờ → NOOP (không tạo thêm) |
| `GET /api/accounts/{id}/gateway/token` | Thêm `request_status` (`NONE`/`PENDING`/`REJECTED`) + `requested_at`. `has_token` = có token **còn hiệu lực** |

**Lưu trữ (migration 0007):** `users.status` thêm `DELETED`; bảng `gateway_token_requests` chỉ thêm dòng (trigger chặn UPDATE/DELETE; sự kiện `REQUESTED`/`APPROVED`/`REJECTED`/`CANCELLED`, trạng thái = sự kiện cuối). **Dọn dữ liệu:** USER là chủ nhiều tài khoản (luồng cũ) → giữ một (cấp giá, hoặc sớm nhất), tài khoản thừa: thu hồi token, bỏ quyền sở hữu, ghi audit `account.dedupe` (actor `migration-0007`); **không đụng** tài khoản thừa đang cấp giá hoặc chế độ cuối SHADOW/LIVE. Thử trên PostgreSQL 16 với dữ liệu giống máy người dùng (Lord Trade chủ `default` + `u-user_cutlot`): giữ `default`, thu hồi token `u-user_cutlot`, tài khoản LIVE thừa giữ nguyên, chạy lại không đổi gì, hạ cấp được.

**Hệ quả an toàn:** USER `DELETED` bị chặn ở mọi chỗ USER `LOCKED` bị chặn (mọi kiểm tra dùng `status != ACTIVE`). Lúc mới cài, USER đầu tiên nhận `default` mà chưa có token → token cũ `GT_INGEST_TOKEN` vẫn chạy cho tới khi ADMIN cấp token đầu tiên cho `default` (giống trước khi có USER).

**Kiểm thử:** `tests/test_admin_users_dec17.py` (xin/cấp/từ chối, xin trùng, khóa, sửa + giữ thuộc tính Keycloak, email trùng, Keycloak lỗi, xóa + chặn sau xóa, không xóa USER cấp giá/LIVE/Gateway đang kết nối, dùng lại tên đăng nhập, SQL + bộ nhớ khớp nhau); `AdminPage.test.tsx`, `AccountPage.test.tsx`; `ops/scripts/e2e_auth.py` (luồng trên Keycloak thật). Thử đột biến 11 chốt chặn: 10 làm test đỏ; chốt kiểm email trùng ở DB không đỏ vì Keycloak kiểm lần hai.
