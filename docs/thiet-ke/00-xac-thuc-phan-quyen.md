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
- **Khởi tạo chủ sở hữu:** khi có người đăng nhập mang role `ADMIN` mà tài khoản `default` chưa có OWNER, người đó được gán OWNER (audit `account.bootstrap_owner`). Đây là cách duy nhất để có OWNER đầu tiên.

## 5. Ma trận quyền (OPS-17)

Vai trò theo tài khoản giao dịch (DB ứng dụng): **VIEWER < OPERATOR < OWNER**. Vai trò hệ thống: **ADMIN** (realm role Keycloak). Kiểm tra ở backend **mỗi request**; giao diện chỉ ẩn hoặc khóa nút cho dễ dùng.

| Hành động | VIEWER | OPERATOR | OWNER | ADMIN (không là thành viên) |
| --- | :-: | :-: | :-: | :-: |
| Xem dữ liệu thị trường, analyst (dùng chung) | ✓ | ✓ | ✓ | ✓ |
| Xem trạng thái, lịch sử Safety/Mode, audit, Gateway **của tài khoản** | ✓ | ✓ | ✓ | ✓ (giám sát) |
| PAUSE / HALT tài khoản | ✗ | ✓ | ✓ | ✓ (hướng an toàn) |
| Resume PAUSED → ACTIVE | ✗ | ✓ | ✓ | ✗ |
| Thoát HALTED (cần tick xác nhận) | ✗ | ✗ | ✓ | ✗ |
| Đổi Mode BACKTEST/PAPER/SHADOW | ✗ | ✗ | ✓ | ✗ |
| Yêu cầu bật LIVE | ✗ | ✗ | ✓ | ✗ |
| **Duyệt** LIVE (người khác người yêu cầu) | ✗ | ✗ | ✓ | ✓ |
| Xoay token Gateway | ✗ | ✗ | ✓ | ✗ (DEC-15) |
| Thêm/đổi vai trò/gỡ thành viên | ✗ | ✗ | ✓ | ✓ |
| Tạo tài khoản giao dịch mới | — | — | — | ✓ |
| Kill switch **toàn hệ thống** (HALT mọi tài khoản) | ✗ | ✗ | ✗ | ✓ |
| Xem audit hệ thống (account = NULL) | ✗ | ✗ | ✗ | ✓ |
| HALT qua CLI break-glass (OPS-15) | — | — | — | Ai có quyền chạy `docker compose exec` trên máy |

Quy tắc:
- Không phải thành viên và không phải ADMIN → **404** (không lộ tài khoản có tồn tại hay không) + audit `access.denied` (MT-C01). Là thành viên nhưng thiếu quyền → **403** + audit (0-C15).
- Không ai được tự gỡ OWNER cuối cùng của một tài khoản.
- Người dùng mất hết vai trò (bị gỡ hoặc bị vô hiệu hóa) không thao tác được nữa. Safety và Guardian vẫn bảo vệ vị thế, vì chúng không phụ thuộc người dùng (MT-C06).
- **Bật LIVE hai bước (0-C16):** OWNER tạo yêu cầu (`POST .../mode/live-requests`, hết hạn sau 15 phút) → **người khác** (so theo `sub` đã xác thực) có quyền duyệt bấm duyệt → lúc này mới gọi `ModeManager` (vẫn kiểm `live_unlocked` và `LIVE_CHECKLIST`). `GT_LIVE_UNLOCKED` vẫn mặc định khóa. Chi tiết duyệt LIVE theo từng tài khoản là MT-08 (GĐ10).

## 6. Safety và Mode theo tài khoản (MT-06)

- Mỗi tài khoản có một `SafetySupervisor` và một `ModeManager` riêng. Quy tắc khôi phục khi khởi động (ACTIVE→PAUSED, HALTED giữ, LIVE→PAPER, SAMPLE chặn SHADOW/LIVE) áp dụng cho **từng** tài khoản.
- **DB là nguồn sự thật:** trước mỗi lần đổi trạng thái, backend khóa theo tài khoản (Postgres `pg_advisory_xact_lock`), đọc trạng thái mới nhất trong DB rồi mới ghi. Một vòng nền mỗi **2 giây** đồng bộ trạng thái từ DB. Nhờ vậy lệnh HALT ghi thẳng vào DB bằng CLI (OPS-15) có hiệu lực với backend đang chạy, và backend không thể ghi đè một HALT bằng ACTIVE cũ.
- Đọc DB lỗi → `allows_new_orders()` trả `False` (mặc định an toàn).
- Kill switch toàn hệ thống: HALT **từng** tài khoản với lý do `GLOBAL_KILL_SWITCH` (audit hệ thống + audit từng tài khoản). Không có lệnh "mở lại toàn bộ": OWNER mở lại từng tài khoản.

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
- `POST /api/accounts/{id}/gateway/token` (OWNER/ADMIN): tạo token mới, **thu hồi mọi token cũ của tài khoản trong cùng transaction**, rồi trả token **đúng một lần**. Giao diện hiện token trong hộp thoại có nút sao chép và cảnh báo "chỉ hiện một lần".
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
| Gateway đọc MT5 login + server + company + loại tài khoản của terminal | **Thiếu** | Heartbeat hiện chỉ có server/company/loại, chưa có login → MT-12 (GĐ1) |
| Gateway kết nối đúng terminal đã cấu hình (nhiều terminal trên một máy) | **Thiếu** | → MT-15 (GĐ1) |
| Bảng liên kết + luồng xác minh có người xác nhận | **Thiếu** | → MT-13 (GĐ1) |
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

**Chưa có:** danh sách/khóa/xóa người dùng trên Dashboard (vẫn làm trên trang quản trị Keycloak); tài khoản giao dịch mới chưa nhận dữ liệu giá và chưa liên kết MT5 (MT-05, MT-12..15, GĐ1).
