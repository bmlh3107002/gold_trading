# GĐ0 — Nền móng

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| CORE-01 | Data contract Pydantic bất biến (`frozen`, `extra=forbid`, datetime có tz → UTC) | `[x]` | `backend/src/gold_trading/contracts/` |
| CORE-02 | Contract → `contracts/openapi.json` → type TS | `[x]` | `backend/scripts/export_openapi.py`, `frontend/src/api/schema.d.ts` |
| CORE-03 | Enum chuẩn `SourceStatus`, `SafetyState`, `TradingMode` (gồm `BACKTEST`) | `[x]` | `common/enums.py` |
| CORE-04 | Tiện ích thời gian/ID | `[x]` | `common/time.py`, `common/ids.py` |
| DB-01 | PostgreSQL/TimescaleDB + Alembic (không sửa migration cũ) | `[x]` | `storage/schema.py`, `backend/migrations/` |
| DB-02 | Bảng append-only Safety/Mode/audit (0001), trigger chặn UPDATE/DELETE | `[x]` | migration `0001` |
| DB-03 | Hypertable `candles` + `candle_quarantine` (0002) | `[x]` | migration `0002` |
| DB-04 | Bảng `analyst_outputs` (0003) | `[x]` | migration `0003` |
| DB-05 | Repository + khôi phục khi khởi động (ACTIVE→PAUSED, HALTED giữ, LIVE→PAPER) | `[x]` | `storage/repository.py` |
| DB-09 | Sao lưu & khôi phục DB: script + lịch tự động + **diễn tập khôi phục** | `[~]` | Service `backup` (`ops/backup/`): mỗi 24 giờ (chờ 5 phút sau khởi động), `pg_dump -Fc` cả DB ứng dụng lẫn DB Keycloak, kiểm `pg_restore --list` + SHA-256, ghi tạm rồi đổi tên, giữ 14 bản, quyền 600; `restore app|keycloak latest` (từ chối file hỏng / khi backend còn chạy). Dashboard cảnh báo khi lỗi/cũ > 26 giờ. Đã diễn tập trong sandbox + CI. **Còn: diễn tập trên Windows (người dùng)** |
| MOD-01 | Mode Manager: LIVE khóa, approver khác actor, đủ `LIVE_CHECKLIST` | `[x]` | `modes/manager.py` |
| MOD-02 | Chặn SHADOW/LIVE khi dùng SAMPLE | `[x]` | `api/app.py` (`mode_guard`) |
| SAF-01 | Safety: ACTIVE/PAUSED/HALTED, ghi trước khi đổi | `[x]` | `safety/supervisor.py` |
| SAF-02 | Safety lưu bền + khôi phục | `[x]` | `storage/repository.py` |
| SAF-03 | Kill switch trên Dashboard, có xác nhận + audit | `[x]` | `POST /api/safety` |
| DSH-01 | Theme CutlotDesk, i18n, responsive. **Chỉ web** (không app mobile/PWA) | `[x]` | `frontend/` |
| DSH-02 | Trang Tổng quan | `[x]` | `frontend/src/pages/` |
| OPS-01 | Docker compose db + backend + frontend, migration tự chạy | `[x]` | `docker-compose.yml`, `deploy/` |
| OPS-02 | Bản deploy build thẳng từ GitHub | `[x]` | `deploy/README.md` |
| OPS-03 | Truy cập qua Tailscale (`DASHBOARD_BIND`), mặc định localhost | `[x]` | Không dùng `0.0.0.0` |
| OPS-04 | Cấu hình qua `.env` (`GT_DATA_SOURCE`, `GT_INGEST_TOKEN`, `GT_BROKER_SESSIONS`, `GT_BROKER_SERVER_TZ`) | `[x]` | |
| OPS-05 | CI GitHub Actions (backend, gateway, frontend, lệch contract, build Docker) | `[x]` | `.github/workflows/ci.yml` — 4/4 xanh |
| OPS-06 | CD tự deploy lên máy Windows | `[!]` | **(hoãn — người dùng)**. Thiết kế đã chốt, xem `PROGRESS.md` 2026-11-06 |
| OPS-07 | Đăng nhập Dashboard + API bằng **Keycloak (OIDC)**: backend làm BFF (Authorization Code + PKCE, client confidential), trình duyệt chỉ giữ cookie phiên `HttpOnly; Secure; SameSite=Strict`, không giữ token; mọi API bắt buộc đăng nhập trừ `/api/health` và cổng ingest (token riêng); actor trong audit lấy từ phiên, không lấy từ request | `[x]` | `auth/` (config, oidc, sessions, web). Phiên trong bộ nhớ, cookie `__Host-gt_session`, làm mới mỗi 60 s, kiểm Origin/Host. Test: `tests/test_auth.py` (Keycloak giả, JWKS cục bộ) |
| OPS-14 | Keycloak trong docker compose: phiên bản ghim cụ thể, realm + client nhập từ file JSON trong repo (không chứa bí mật), DB riêng, chạy sau reverse proxy cùng origin, sao lưu cùng DB-09 | `[x]` | Keycloak 26.8.2 (`ops/keycloak/`), DB riêng `keycloak-db` (postgres 16.14), nginx `/auth/`, brute force bật, `check_realm.py` trong CI, `sync-client.sh`. DB Keycloak có trong sao lưu (DB-09). E2E với Keycloak thật: `ops/scripts/ci_stack.sh` |
| OPS-15 | **Lối dừng khẩn cấp khi Keycloak hỏng:** lệnh CLI trong container backend chỉ cho phép HALT (không cho ACTIVE/LIVE), có audit `actor=break-glass` | `[x]` | `gt-break-glass status|halt --account X|--all` (`safety/break_glass.py`): chỉ HALT, ghi thẳng DB, `actor=break-glass`; backend nhận trong ~2 s. Test quét AST: không resume/mode/ACTIVE |
| OPS-16 | HTTPS cho truy cập từ máy khác qua **Tailscale Serve** (tên `*.ts.net`), cookie `Secure`, redirect URI đúng; `localhost` dùng cho phát triển | `[~]` | Backend từ chối `GT_PUBLIC_URL` http ngoài localhost; nginx chuyển `X-Forwarded-Proto` của Tailscale Serve (đã xác minh mã nguồn Tailscale gửi `https`); hướng dẫn `deploy/README.md` (Tailscale Serve thay `DASHBOARD_BIND`). **Còn: người dùng bật Serve và đăng nhập HTTPS trên Windows + điện thoại** |
| OPS-17 | **Phân quyền:** ~~RBAC OWNER/OPERATOR/VIEWER + ma trận quyền~~ → **DEC-16:** chỉ `ADMIN` (realm role Keycloak; quản lý tài khoản, duyệt LIVE) và `USER` (giao dịch trên tài khoản của mình, ACTIVE/LOCKED); kiểm ở backend mỗi request | `[x]` | `accounts/access.py`, `api/accounts.py` (`Guard.check`), `api/users.py`. Thiết kế mục 5, 16 của `docs/thiet-ke/00-xac-thuc-phan-quyen.md`. LIVE: USER xin, ADMIN duyệt/từ chối |
| OPS-11 | Log có cấu trúc, xoay vòng log, không ghi token/mật khẩu vào log | `[x]` | `ops/logging.py`: JSON một dòng (`GT_LOG_FORMAT=json` trong image), `correlation_id` từ `X-Request-ID` của nginx, access log tự ghi không có query string, che bí mật cho mọi logger; compose giới hạn 5 × 10 MB mỗi service; nginx log không query/header |
| OPS-12 | Kiểm tra đồng hồ máy chủ (NTP): lệch > 2 giây → cảnh báo; > 30 giây → chặn nạp realtime | `[x]` | `ops/clock.py`: trung vị header `Date` của 5 máy chủ HTTPS (≥ 3 nguồn), mỗi 5 phút (1 phút khi lệch). > 2 s cảnh báo, > 30 s ingest nến 503 (nhịp tim vẫn nhận); không đo được → cảnh báo, không chặn (`GT_CLOCK_UNKNOWN_BLOCKS=1` để chặn). `GET /api/system/health`, banner trên Dashboard |
| GW-05 | Đổi token ingest (token cũ đã lộ trong chat) | `[x]` | Người dùng đã đổi trên máy Windows (xác nhận 2026-11-06), không cần hỏi lại. Token theo từng tài khoản, lưu băm, xoay từ giao diện là việc MT-04 |

**Case GĐ0**

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 0-C01 | Backend khởi động lại khi đang ACTIVE | Về PAUSED, ghi `STARTUP_REQUIRES_REVIEW` | `[x]` |
| 0-C02 | Khởi động lại khi đang LIVE | Về PAPER, ghi audit | `[x]` |
| 0-C03 | UPDATE/DELETE trực tiếp vào bảng append-only | DB chặn | `[x]` |
| 0-C04 | Mất volume DB / ổ đĩa hỏng | Khôi phục từ bản sao lưu gần nhất theo hướng dẫn; Safety giữ PAUSED | `[x]` Diễn tập: `ops/scripts/ci_stack.sh` bước 3 (phá bảng → khôi phục cả hai DB → dữ liệu khớp, trigger còn, đăng nhập lại được); khởi động sau khôi phục theo quy tắc ACTIVE→PAUSED |
| 0-C05 | Ổ đĩa đầy | Cảnh báo trước ở 85%; khi đầy, ingest báo lỗi rõ, không mất dữ liệu đã ghi | `[x]` `tests/test_storage_health.py` (cảnh báo > 85%, DB không ghi được → ingest 503, dữ liệu cũ còn, gửi lại được) |
| 0-C06 | Thiếu `GT_INGEST_TOKEN` hoặc token < 24 ký tự | Cổng ingest tắt (503) | `[x]` |
| 0-C07 | Cấu hình `.env` sai cú pháp (lịch broker, múi giờ) | Backend không khởi động, báo lỗi rõ | `[x]` |
| 0-C08 | Truy cập không đăng nhập / sai mật khẩu nhiều lần | 401 + chuyển tới đăng nhập; Keycloak khóa tạm (brute force detection); audit | `[x]` 401: `test_every_non_public_route_requires_session`; brute force trên Keycloak thật: `ops/scripts/e2e_auth.py` (đúng mật khẩu vẫn bị khóa tạm sau nhiều lần sai); Keycloak ghi event LOGIN_ERROR |
| 0-C11 | Keycloak chết / không truy cập được | Không đăng nhập mới được; phiên đang có chạy tới hết hạn; **HALT vẫn làm được qua OPS-15**; Safety không bao giờ tự sang ACTIVE | `[x]` `tests/test_break_glass.py::test_halt_works_while_keycloak_is_down_and_running_app_sees_it`, `test_auth.py::test_keycloak_down_keeps_existing_session_until_expiry` |
| 0-C12 | Phiên hết hạn / làm mới thất bại / người dùng bị vô hiệu hóa trên Keycloak | 401, đăng nhập lại; người bị vô hiệu không thao tác được nữa | `[x]` `test_disabled_user_loses_access_at_next_refresh`, `test_idle_timeout_and_max_lifetime` |
| 0-C13 | Bị thu hồi quyền sở hữu / bị khóa khi đang đăng nhập | Request sau bị chặn ngay (kiểm ở DB mỗi request) | `[x]` `tests/test_rbac.py`: `test_ownership_revocation_takes_effect_on_next_request`, `test_locked_user_cannot_act_but_safety_state_is_kept` |
| 0-C14 | Request từ trang web khác (CSRF), Origin lạ, DNS rebinding | Từ chối (SameSite=Strict + kiểm Origin/Host) | `[x]` `test_write_from_other_origin_is_blocked_and_audited`, `test_unknown_host_rejected_dns_rebinding`, `test_callback_without_login_cookie_is_rejected` |
| 0-C15 | ~~`VIEWER` gọi API ghi~~ → DEC-16: vai trò cũ (OPERATOR/VIEWER) hoặc ADMIN gọi API tài khoản giao dịch | 404 + audit lần bị từ chối, không cho quyền gì | `[x]` `tests/test_rbac.py`: `test_legacy_operator_and_viewer_rows_grant_nothing`, `test_admin_cannot_touch_any_trading_account_even_with_legacy_membership` |
| 0-C16 | Bật LIVE: người không phải ADMIN duyệt, người xin bị khóa/không còn là chủ, checklist thiếu, hết hạn | Từ chối (dựa trên danh tính đã xác thực) | `[x]` `tests/test_rbac.py`: `test_only_admin_approves_or_rejects_live`, `test_live_approval_rules`, `test_live_request_expires` |
| 0-C17 | Đồng hồ lệch làm JWT bị coi là hết hạn/chưa hiệu lực | Cho lệch tối đa vài giây; quá thì từ chối + cảnh báo (liên quan OPS-12) | `[x]` `test_clock_skew_within_leeway_accepted_beyond_rejected` (lệch ≤ 5 s) |
| 0-C18 | Token/mật khẩu xuất hiện trong log | Không bao giờ: test quét log | `[x]` `tests/test_logging.py::test_no_secret_in_logs_after_full_flow` (đăng nhập, callback, làm mới, ingest, xoay token, đăng xuất, log cố ý chứa bí mật); thử đột biến tắt che → 11 test đỏ |
| 0-C19 | Sao lưu chạy khi dịch vụ chưa khởi tạo xong (DB Keycloak còn trống) | Chờ 5 phút sau khởi động mới sao lưu lần đầu (phát hiện khi diễn tập) | `[x]` `ops/backup/backup.sh` (`GT_BACKUP_START_DELAY_S`) |
| 0-C20 | Khôi phục từ file hỏng, hoặc khi backend/Keycloak còn chạy | Từ chối, báo rõ, không đụng DB | `[x]` diễn tập trong sandbox (file sửa 1 byte → "SHA-256 KHÔNG KHỚP"; backend chạy → "Còn 2 kết nối") |
| 0-C21 | Mode lưu dạng chuỗi `"LIVE"` (không phải enum) khi khởi động | Vẫn về PAPER (lỗi tìm được khi soát) | `[x]` `tests/test_storage.py::test_restore_mode_normalizes_string_live` |
| 0-C09 | Đồng hồ máy lệch | Cảnh báo / chặn nạp realtime (OPS-12) | `[x]` `tests/test_clock.py` (OK/WARN/BLOCKED, nguồn sai, thiếu nguồn, chặn rồi mở lại ingest) |
| 0-C10 | CI đỏ | Không deploy (khi có CD) | `[x]` (CI) |

**Gate GĐ0:** OPS-07, OPS-11, OPS-12, OPS-14..17, DB-09 và các việc MT ghi "GĐ0" xong; mọi case 0-C01..C21 và MT-C01..C04, MT-C06, MT-C15 có test; người dùng đã đăng nhập bằng Keycloak qua HTTPS trên máy Windows và điện thoại, diễn tập HALT khi Keycloak tắt, diễn tập khôi phục DB (gồm DB Keycloak). OPS-06 (CD) vẫn hoãn, không chặn Gate.

## Việc tiếp theo của GĐ0

**GĐ0: code xong, chờ người dùng làm các bước trên máy Windows để đạt Gate** (mỗi lần một bước, theo `deploy/README.md`): (1) cập nhật compose + `.env` bí mật + `docker compose up -d --build`; (2) bật Tailscale Serve, đặt `GT_PUBLIC_URL`, đăng nhập Keycloak lần đầu; (3) đăng nhập trên máy tính và điện thoại qua `https://….ts.net`; (4) tạo token Gateway trên Dashboard, cập nhật `gateway.env`, chạy lại Gateway, xác nhận dữ liệu về; (5) diễn tập tắt Keycloak → `gt-break-glass halt` → bật lại; (6) diễn tập khôi phục cả hai DB. Sau khi người dùng xác nhận đóng GĐ0 → GĐ1 (cần chốt DEC-01..07). Lộ trình cũ để tham khảo: ① dữ liệu giá ✅ → ② biểu đồ ✅ → ③ Technical analyst ✅ → MT5 Gateway chỉ đọc ✅ (đã chạy với MT5 demo thật) → **③b Hồ sơ rủi ro + Kế hoạch giao dịch** → Event & calendar analyst → ④ MarketView đầu tiên → ⑤ Strategy → ⑥ Backtest → ⑦ MT5 thật (để sau).

## Nhật ký

> Toàn bộ nhật ký từ lúc dựng khung tới khi đóng GĐ0 (chuyển từ `PROGRESS.md`).


### 2026-11-05 — Dựng khung
- Tạo nhánh `develop` từ `main`, xóa `.DS_Store`.
- Dựng toàn bộ khung đã liệt kê ở trên.
- Đã chạy thử backend và dashboard: Resume/HALT hoạt động, chọn LIVE bị từ chối đúng.

### 2026-11-05 — Docker
- Thêm Dockerfile cho backend và frontend (nginx), `docker-compose.yml` ở gốc (build từ code local), và `deploy/docker-compose.yml` + `deploy/README.md` (build thẳng từ GitHub, không cần clone).
- Đã build và chạy thử: backend healthy, dashboard 200, `/api` qua nginx hoạt động, kill switch hoạt động.
- Đổi nhánh mặc định GitHub sang `develop`. `CLAUDE.md` import `@PROGRESS.md`.

### 2026-11-05 — Theme AurumDesk cho Dashboard
- Viết lại phần giao diện `frontend/` theo theme AurumDesk. Logic gọi API, polling 3s và payload gửi backend giữ nguyên; backend không đổi.
- Thêm i18next, lucide-react, @fontsource/inter. Thêm ESLint 9 và Vitest + Testing Library (17 test).
- Thay `window.confirm` bằng Dialog. Dừng khẩn cấp, mở lại từ HALTED (cần tick xác nhận) và chuyển LIVE đều phải xác nhận.
- Đã kiểm tra bằng ảnh chụp: desktop 1440, tablet 900, mobile 390, dark/light, mất kết nối, lỗi tải, dialog. Không có tràn ngang.
- Lưu ý: prompt theme nhắc Binance/XAUUSDT, nhưng dự án dùng MT5/XAUUSD nên giữ XAUUSD. Chưa có biểu đồ nến/EMA/RSI vì chưa có dữ liệu giá; token màu chart đã khai báo sẵn.

### 2026-11-05 — Database
- Thêm PostgreSQL vào cả hai file compose. Backend lưu lịch sử Safety, Mode và audit vào DB, migration Alembic `0001`, trigger append-only.
- API: `/api/audit`, health kiểm tra DB, `storage` trong status. Dashboard hiện "Lưu trữ: PostgreSQL" ở chân sidebar.
- Đã kiểm tra bằng Docker thật: migration chạy; restart backend thì ACTIVE về PAUSED và mode được giữ; `down` + `up` vẫn còn HALTED; UPDATE/DELETE trực tiếp bị DB chặn.

### 2026-11-05 — Gom tên Docker
- Đổi tên project compose `gold-trading` → `gold_trading`, đặt tên image cố định `gold_trading/backend:latest` và `gold_trading/frontend:latest`. `deploy/README.md` có thêm hướng dẫn tìm và dọn dẹp.

### 2026-11-05 — Dữ liệu giá và trang Thị trường (bước ① + ②)
- Cửa nạp nến chung, migration `0002` (hypertable `candles`, `candle_quarantine`, append-only), lịch thị trường, EMA/RSI, API thị trường.
- Nguồn dữ liệu mẫu tất định chạy nền (nạp bù 90 ngày, rồi thêm nến khi nến đóng). Nguồn CSV kèm CLI `import-csv`.
- Frontend: trang Thị trường, header có giá thật, điều hướng bằng hash.
- Đã kiểm tra bằng Docker thật: migration 0002, hypertable, 5.883 nến mẫu; restart không sinh trùng; SHADOW bị từ chối khi dùng dữ liệu mẫu; CLI nạp CSV cách ly nến lỗi và từ chối file thiếu múi giờ; UPDATE trên `candles` bị chặn.

### 2026-11-05 — MT5 Gateway bản chỉ đọc
- Xóa khung `adapter.py` cũ (có kiểu dữ liệu đặt lệnh). Viết Gateway chỉ đọc: `timeconv`, `reader` (bọc chỉ đọc), `backend_client`, `checks` (9 bước, gợi ý múi giờ IANA), `sync`, `cli`, `gateway.env.example`, `README.md` hướng dẫn Windows.
- Backend: cổng nhận dữ liệu có token, chạy thử không lưu, R1, nhịp tim và trạng thái Gateway. Giao diện: trạng thái MT5 ở sidebar. nginx `client_max_body_size 5m`. Compose thêm `GT_INGEST_TOKEN`.
- Kiểm chứng bằng MT5 giả lập và Docker + Postgres qua nginx: xem mục 7 của thiết kế. **Người dùng sẽ chạy lần đầu với MT5 demo thật (XAUUSD) trên Windows.**

### 2026-11-05 — Bước ③: Technical analyst v1
- Ghi **Nguyên tắc thận trọng tài chính** vào `CLAUDE.md`. Thiết kế chi tiết: `docs/thiet-ke/03-technical-analyst.md`.
- Thêm R1 (kiểm tra múi giờ khi nạp CSV), R2–R6 (`market/quality.py`), ATR Wilder, analyst, bảng `analyst_outputs` (migration 0003), runner nền, API, thẻ giao diện và đường S/R trên biểu đồ.
- Kiểm chứng: đối chiếu thư viện `ta` (ATR lệch 5e-11); tái lập 40/40 kết quả sau khi thêm dữ liệu tương lai; Docker + Postgres OK. Sửa lỗi tooltip làm tràn ngang trên mobile.

### 2026-11-05 — Soát lỗi bước ① + ②
- Đã kiểm tra bằng kịch bản riêng: số nến mỗi tuần đúng 460, kể cả tuần Mỹ đổi giờ; không có nến ngoài phiên; EMA/RSI không đổi theo độ dài warm-up (lệch 0); point-in-time đúng.
- Đã sửa: (1) trùng khóa mâu thuẫn trong cùng file từng tạo revision giả; (2) báo nhầm "giá cũ" lúc mở cửa đầu tuần; (3) che mất sự cố nguồn dữ liệu vào cuối tuần; (4) mốc 24h có thể lệch 1 nến; (5) CLI cho chọn H4 dù căn khung sai; (6) trục biểu đồ thiếu ngày, phần trăm thiếu dấu +.
- Giới hạn còn lại: lịch thị trường chưa có ngày lễ/lịch riêng broker; giá lưu kiểu float (đủ cho hiển thị, PnL sau này phải dùng Decimal); chưa hỗ trợ H4/D1 theo giờ server.

### 2026-11-05 — Chạy MT5 Gateway với MT5 demo thật + sửa lịch giờ broker
- Người dùng chạy trên Windows: Docker (`GT_DATA_SOURCE=MT5`), MetaQuotes-Demo, XAUUSD M15. `mt5-gateway check` đạt 9/9 (giờ server khớp GMT+2 bằng tick sống, R1 0,00% trên 5.000 nến đi qua cả hai lần đổi giờ). `run`: nạp 5.000 nến, 0 trùng, 0 cách ly; heartbeat CONNECTED/DEMO/read_only.
- **Lỗi tìm được:** Technical analyst bị chặn vĩnh viễn (`LOW_COVERAGE`, độ phủ 0,9615). Kịch bản chẩn đoán chỉ đọc trên DB thật: thiếu đúng 4 nến/ngày lúc 23:00–23:45 giờ server (16:00–16:45 NY), tổng 210; ngày 07/09 (Labor Day) thiếu 10. Specification của broker: Quotes Mon–Fri 00:00–23:00 giờ server. Lịch tham chiếu nghỉ 1 giờ, broker nghỉ thêm 1 giờ.
- **Sửa:** `BrokerSessions` + `MarketCalendar` (tham chiếu ∩ broker) dùng cho R2, độ mới dữ liệu và nhãn phiên. Cờ chặn mới `CALENDAR_MISMATCH` khi có nến ở chỗ lịch nói đóng (lưới an toàn cho khai báo sai). `technical-1.1.0`. Không tự suy lịch từ dữ liệu (sẽ che sự cố mất dữ liệu lặp lại). Lý do ghi ở `docs/thiet-ke/03-technical-analyst.md`.
- Kiểm chứng: 31 test mới (cú pháp, mùa hè/đông, tuần lệch DST 26–30/10, thứ Sáu đóng sớm, mất dữ liệu giữa phiên vẫn bị bắt, khai báo sai lịch/múi giờ bị chặn, cấu hình sai → không khởi động). Mô phỏng toàn bộ lịch sử 18/08–05/11 khớp **chính xác** số liệu thật (5.000 nến có, 210 thiếu, cùng phân bố theo thứ). Kịch bản đầu cuối qua API: lịch cũ → INVALID 0,9615; lịch broker → HEALTHY, độ phủ 1,0.
- Sửa câu "Dữ liệu mẫu sẽ tự nạp" bị sai khi dùng MT5.
- **Đã xác nhận trên máy người dùng** (Docker build lại từ `develop`, `.env` có `GT_BROKER_SESSIONS=Mon-Fri 00:00-23:00`, `GT_BROKER_SERVER_TZ=Europe/Athens`): `technical-1.1.0` HEALTHY, độ phủ 1,0, 0 nến thiếu, 0 nến ngoài lịch; confidence 0,5 do spike 04/11 23:00 UTC (R3). Backend khởi động lại → Gateway tự thử lại và kết nối lại; nến 22:30–22:45 (giờ VN) về sau khi đóng khoảng 9 giây.
- Quan sát cần soát: `cluster_levels` gộp chuỗi swing thành vùng 3.891–3.951 (rộng ~5 ATR, 27 lần chạm) — vùng quá rộng không có ý nghĩa hỗ trợ/kháng cự; spike có thể tạo swing giả.
- Giới hạn còn lại: lịch broker phải chép tay (MT5 Python không đọc được Sessions); chưa có ngày lễ; trục thời gian biểu đồ đặt vạch ngày theo UTC nhưng ghi nhãn giờ máy (vạch "05/11" nằm ở 07:00 giờ VN) — chỉ là hiển thị; spike ở nến mở lại sau giờ nghỉ (01:00 server 04/11) chỉ gắn cờ.

### 2026-11-05 — Bước 00: soát Technical analyst trên dữ liệu thật
- `technical-1.2.0`: vùng S/R không rộng quá 1 ATR (trước đây gộp dây chuyền ra vùng ~5 ATR trên dữ liệu thật); bỏ swing nằm trên nến spike. Lý do ở `docs/thiet-ke/03-technical-analyst.md`. Test tính tay cho phép gộp, test spike tạo hỗ trợ giả; đã xác nhận test mới **thất bại trên code cũ**.
- Biểu đồ: vạch ngày nay đặt theo nửa đêm giờ máy người xem (`components/chart/chartTime.ts` dời mốc theo độ lệch múi giờ của từng mốc). Nếu DST làm giờ bị lặp thì giữ nguyên UTC để thư viện không lỗi. Test: giờ VN, New York lùi/tiến đồng hồ. Kiểm tra bằng ảnh chụp với múi giờ Asia/Ho_Chi_Minh: vạch "05/11" trùng nến 00:00 05/11.
- Kết quả: backend 164 passed, frontend 35 passed, ruff/tsc/eslint sạch, build OK.
- **Đã xác nhận trên máy người dùng:** `technical-1.2.0` HEALTHY, atr14 = 13,44; 12 vùng S/R, vùng rộng nhất 12,09 (≤ 1 ATR). Vùng cũ 3.891–3.951 (27 chạm) tách thành 5 vùng (tổng 26 chạm: swing trên nến spike 04/11 đã bị loại).

### 2026-11-05 — Truy cập dashboard qua Tailscale
- Người dùng muốn mở dashboard từ máy khác qua Tailscale. Thêm `DASHBOARD_BIND` (mặc định `127.0.0.1`) vào cả hai file compose; hướng dẫn ở `deploy/README.md` (đặt IP Tailscale, hoặc `tailscale serve`). Cố ý không mở `0.0.0.0`: API chưa có xác thực, ai cùng Wi-Fi cũng điều khiển được Safety/Mode. Kiểm tra bằng `docker compose config` (mặc định và có IP).
- Nhắc lại: **xác thực API** (việc 5) cần làm trước khi mở rộng truy cập hơn nữa.

### 2026-11-06 — CI (GitHub Actions)
- `.github/workflows/ci.yml`: chạy khi push `develop`/`main` và PR. Bốn job: backend (ruff, pytest, OpenAPI không lệch), mt5_gateway (pytest), frontend (type TS không lệch, `npm run check`, build), docker (build hai image). Lần chạy đầu tiên: **4/4 xanh**.
- **CD (máy Windows tự cập nhật) — tạm hoãn theo yêu cầu người dùng.** Đã chốt cách làm: Task Scheduler mỗi 5 phút hỏi GitHub; chỉ deploy commit `develop` có CI xanh; build đúng commit đó (`GT_BRANCH=<sha>`); kiểm tra `/api/health`; không deploy khi mode LIVE; không thử lại commit lỗi; không dùng self-hosted runner (repo public). Script PowerShell phải chỉ dùng ký tự ASCII (Windows PowerShell 5.1) và được test trên runner `windows-latest` trong CI (sandbox không chạy được PowerShell).

### 2026-11-06 — Checklist theo giai đoạn
- Người dùng chốt cách làm **"đi sạch từng giai đoạn"**: xong hết một giai đoạn (mọi phần, mọi nguồn dữ liệu của mô hình, mọi case có test, Gate đạt) rồi mới sang giai đoạn sau.
- Viết lại `CHECKLIST.md` thành 11 giai đoạn theo luồng mô hình (GĐ0 nền móng → GĐ1 dữ liệu vào đủ 4 nhóm nguồn → … → GĐ10 LIVE), ~200 mã việc, ~120 case, 10 quyết định `DEC-xx` chờ người dùng. Không mã cũ nào bị mất.
- **Giai đoạn hiện tại: GĐ0** (còn: xác thực Dashboard/API, log, kiểm tra đồng hồ, sao lưu + diễn tập khôi phục, xác nhận đổi token). Sau đó GĐ1 cần người dùng chốt DEC-01..07 (nguồn lịch kinh tế, tin tức, DXY, kỳ vọng Fed, NHTW/ETF, ngân sách, khóa API).

### 2026-11-06 — Một người dùng, bảo mật để sau
- Người dùng chốt: **hiện chỉ một người dùng**, chưa ưu tiên bảo mật. `OPS-07` (đăng nhập), `GW-05` (đổi token), case `0-C08` → **hoãn**, không chặn Gate GĐ0. Trong lúc hoãn vẫn không mở `0.0.0.0`; Tailscale là lớp bảo vệ duy nhất.
- Mục tiêu sau này: **nhiều người, mỗi người một tài khoản riêng** (vốn, MT5, rủi ro, lệnh riêng). Ghi vào `CHECKLIST.md` phần **MT** (MT-01..11, MT-C01..C07, DEC-11..14), để sau; nên làm trước GĐ8 và trước khi có người dùng thứ hai.
- GĐ0 còn: `OPS-11` (log), `OPS-12` (đồng hồ), `DB-09` (sao lưu + diễn tập khôi phục), case 0-C04/C05/C09.

### 2026-11-06 — Đổi quyết định: làm bảo mật + phân quyền ngay trong GĐ0, dùng Keycloak
- Người dùng chốt: GĐ0 làm **đầy đủ** đăng nhập (Keycloak, OIDC), phân quyền theo vai trò và nền móng đa người dùng (mỗi người một tài khoản giao dịch riêng). Thay cho quyết định "hoãn bảo mật" trước đó.
- `CHECKLIST.md`: thêm OPS-14..17 (Keycloak trong compose, lối HALT khi Keycloak hỏng, HTTPS qua Tailscale Serve, RBAC), case 0-C11..C18; MT-01..04, 06, 09..11 làm trong GĐ0; MT-05 → GĐ1, MT-07 → GĐ5, MT-08 → GĐ10. Gate GĐ0 cập nhật.
- Prompt cho phiên làm GĐ0: `docs/prompts/GD0-hoan-thien-nen-mong.md`.
- `GW-05` xong: người dùng đã đổi token ingest trên máy Windows.

### 2026-11-06 — GĐ0: Keycloak + đăng nhập + phân quyền + đa tài khoản + log + đồng hồ + sao lưu
- Người dùng chốt: DEC-11 người thân/bạn bè, hệ thống tự giao dịch; DEC-12 **chưa trả lời** → `GT_MULTI_USER_ENABLED=0` (chưa nhận người thứ hai); DEC-13 chạy trên máy Windows, gom mọi Gateway về một máy; phiên 8 giờ / 30 phút; **chưa bật OTP**; đang truy cập bằng `http://100.x.y.z:8080` → chuyển sang Tailscale Serve (HTTPS); push `develop` như trước, CD để sau.
- Thiết kế đã duyệt: `docs/thiet-ke/00-xac-thuc-phan-quyen.md`.
- **OPS-14:** Keycloak 26.8.2 (`ops/keycloak/`), DB riêng, realm JSON không bí mật (CI kiểm bằng `check_realm.py`), nginx `/auth/`. Đã chạy thật trong sandbox: realm nhập, secret khớp `.env`, admin có role ADMIN + bắt đổi mật khẩu.
- **OPS-07:** BFF (`backend/src/gold_trading/auth/`), mọi route bắt buộc đăng nhập (test duyệt mọi route trong OpenAPI), bỏ `actor`/`approver` khỏi request (gửi lên → 422). Frontend: trang đăng nhập, nút đăng xuất, bỏ ô "Người thao tác". Lưu ý FastAPI 0.162 gói router được include thành `_IncludedRouter` (không thấy trong `app.routes`): liệt kê route qua `app.openapi()`.
- **MT-01/02:** migration `0004` (users, trading_accounts, account_members, gateway_tokens; `account_id` cho Safety/Mode/audit). Kiểm trên TimescaleDB thật: dữ liệu cũ → `default`, trigger append-only còn, schema khớp migration.
- **OPS-17/MT-03/MT-06:** ma trận quyền `accounts/access.py`, API `/api/accounts/{id}/...`, Safety/Mode riêng từng tài khoản (DB là nguồn sự thật, đồng bộ 2 s), LIVE hai bước, kill switch toàn hệ thống. Frontend: chọn tài khoản, nút khóa theo quyền, duyệt LIVE. Thử đột biến (bỏ kiểm quyền) → 10 test đỏ.
- **OPS-15:** `gt-break-glass` (chỉ HALT). **MT-04/09/10/11:** token Gateway theo tài khoản (băm, xoay), trang Tài khoản, quản lý thành viên (chặn người thứ hai theo DEC-12). **OPS-12:** kiểm đồng hồ. **OPS-11:** log JSON + che bí mật. **DB-09:** service `backup` + `restore`.
- **Kiểm chứng bằng Docker thật (sandbox):** `ops/scripts/ci_stack.sh` — đăng nhập Keycloak thật 20/20, break-glass khi Keycloak tắt, sao lưu → phá bảng → khôi phục cả hai DB → dữ liệu khớp + đăng nhập lại 18/18, quét log không thấy bí mật. Chạy trong CI (job docker).
- **Lỗi tìm được khi diễn tập sao lưu:** (1) bản sao lưu đầu chạy ngay lúc khởi động, khi Keycloak chưa tạo bảng → thêm chờ 5 phút; (2) `sha256sum --status` không có trên busybox (image Alpine) → khôi phục luôn từ chối (an toàn nhưng không dùng được) → so sánh băm trực tiếp; (3) worker nền TimescaleDB bị đếm là "kết nối còn mở" → chỉ đếm `client backend`, `DROP DATABASE ... WITH (FORCE)`; (4) file dump quyền 666 → `umask 077`. Lần đăng nhập đầu Keycloak yêu cầu thêm bước bổ sung email/họ tên (VERIFY_PROFILE).
- **Lỗi tìm được khi soát:** `InMemoryRepository.last_mode` trả chuỗi, `restore_mode` so `is TradingMode.LIVE` → LIVE có thể được khôi phục sau restart ở bản bộ nhớ (bản SQL không bị). Đã sửa cả hai chỗ + test.

### 2026-11-06 — Yêu cầu chính thức: luồng đăng nhập → liên kết MT5 → giao dịch đúng MT5
- Người dùng chốt yêu cầu: mỗi người đăng nhập riêng → liên kết với MT5 của mình qua Gateway → backend lưu liên kết `(MT5 login, server, Gateway)` → lệnh chỉ đi tới đúng Gateway/MT5 đã liên kết → trước mọi đặt/sửa/hủy/đóng lệnh kiểm tra login + server thực tế trong terminal; lệch, mất kết nối hay sai liên kết thì chặn, cảnh báo, xác minh lại, không tự chuyển. Lệnh, vị thế, vốn, hạn mức, Safety, Mode, lịch sử tách theo tài khoản; thiếu liên kết thì không dùng MT5 chính hay Gateway người khác.
- Ghi vào `docs/thiet-ke/00-xac-thuc-phan-quyen.md` mục 14 (yêu cầu, đã có/còn thiếu, trạng thái liên kết, thực thi, bất biến). `CHECKLIST.md`: MT-12..MT-15 (GĐ1: đọc danh tính terminal, bảng liên kết + xác nhận, phát hiện lệch, đúng terminal), MT-16 (GĐ8), MT-17/18 (GĐ9: định tuyến + kiểm danh tính trước mọi thao tác), case MT-C08..C15, bổ sung Gate GĐ1/GĐ8/GĐ9.
- **Rõ ràng:** token Gateway theo tài khoản (MT-04) chỉ xác thực chương trình gửi, **không** phải xác minh MT5. Luồng giao dịch riêng từng người **chưa hoàn thành**. `mt5_gateway` vẫn chỉ đọc; thực thi lệnh là package riêng (GW-10, GĐ9).
- **MT-19 (GĐ0, xong):** chỉ có một tài khoản giao dịch thì không hiện bộ chọn, tự dùng tài khoản của mình. Frontend 46 passed.

### 2026-11-06 — Cài GĐ0 trên máy Windows mới + theme đăng nhập + đổi tên
- Người dùng làm xong trên máy Windows mới: `.env` bí mật, Docker 6/6 healthy, đăng nhập lần đầu (Chủ "Tài khoản chính"), MT5 Gateway check 9/9 + run (5.000 nến, 0 cách ly), Tailscale Serve `https://k.….ts.net` + `sync-client.sh`, đăng nhập trên máy tính và iPhone (OPS-16), diễn tập break-glass khi tắt Keycloak (HALTED, lịch sử ghi `break-glass`).
- Theme đăng nhập Keycloak kế thừa `keycloak.v2` (`ops/keycloak/themes/cutlotdesk`, CI `check_theme.py` so màu với `tokens.css`). Đổi tên AurumDesk → **CutlotDesk** (đọc dự phòng khóa localStorage cũ). Realm còn tên theme cũ thì Keycloak dùng theme mặc định; `sync-client.sh` đặt lại.
- **DEC-12 chốt:** người dùng chấp nhận rủi ro pháp lý, chỉ dùng nội bộ (bản thân và người thân), không giới hạn số người → bật `GT_MULTI_USER_ENABLED=1` trên máy người dùng (mặc định trong code vẫn `0`).
- **MT-20:** ADMIN tạo người dùng trên Dashboard (menu **Quản trị** chỉ ADMIN thấy) → Keycloak (mật khẩu tạm, bắt đổi) + tài khoản giao dịch riêng `u-<username>`, người đó là Chủ. Thiết kế mục 15 của `docs/thiet-ke/00-xac-thuc-phan-quyen.md`. Keycloak 26.8 cần scope tùy chọn `kc-admin-api` cho Admin API (tìm được khi chạy thật). **Lỗi tìm được:** lỗi 422 của FastAPI trả nguyên giá trị đã gửi (có thể lộ mật khẩu) → handler toàn cục bỏ `input`. Kiểm chứng: backend 328 passed, frontend 57 passed, Keycloak thật (realm cũ + `sync-client.sh`, cài mới), `ci_stack.sh` 27/27 + 18/18 + không có bí mật trong log. Máy người dùng cần: build lại + `sync-client.sh`.
- Còn lại của Gate GĐ0: diễn tập sao lưu + khôi phục trên máy người dùng (DB-09).

### 2026-11-06 — Diễn tập trên máy người dùng: MT-20 đạt; DEC-15 ẩn token Gateway với admin
- **MT-20 kiểm chứng trên máy người dùng:** build lại `backend frontend keycloak` (healthy), `sync-client.sh` báo "quyền tạo người dùng cho backend.", ADMIN tạo `thunghiem` trên menu Quản trị → đăng nhập ẩn danh bị bắt đổi mật khẩu, chỉ thấy tài khoản riêng, không có menu Quản trị. ADMIN thấy cả hai tài khoản trong ô chọn.
- Người dùng tạo thêm người giao dịch ("Lord Trade") và thêm làm **Chủ** "Tài khoản chính" (token + MT5 giữ nguyên vì gắn theo tài khoản, không theo người dùng).
- **DEC-15** (người dùng chốt): `admin` chỉ quản trị, không giao dịch; **ẩn token Gateway với admin**. Code: bỏ `ROTATE_TOKEN` khỏi `ADMIN_PERMS` (chặt hơn = an toàn hơn), Dashboard chỉ hiện mục MT5 Gateway khi có `ROTATE_TOKEN` (Chủ). Ma trận quyền ở `docs/thiet-ke/00-xac-thuc-phan-quyen.md` mục 5 sửa theo (test so khớp). Test: `test_rotate_requires_owner_or_admin` (admin không là thành viên → 403, không sinh token; tự thêm làm Chủ thì được), `AccountPage.test.tsx` (ẩn mục, không gọi API token). Kiểm chứng: backend 328 passed, frontend 58 passed, ruff/tsc/eslint sạch, build OK.
- Yêu cầu ghi cho GĐ1 (MT-15): một máy chạy nhiều MT5, mỗi người chỉ thao tác MT5 của mình, mong muốn một Gateway quản lý nhiều terminal. Đặt lệnh chỉ tới MT5 của đúng tài khoản (GĐ9).
- **Còn:** người dùng gỡ `admin` khỏi "Tài khoản chính", build lại để nhận DEC-15, rồi diễn tập sao lưu + khôi phục (DB-09).

### 2026-11-06 — DEC-16: đơn giản hóa phân quyền, chỉ ADMIN và USER
- **Người dùng yêu cầu:** chỉ hai vai trò; ADMIN chỉ quản lý tài khoản (danh sách, tạo, khóa, mở khóa, đặt lại mật khẩu), không giao dịch; USER giao dịch bằng token Gateway riêng; bỏ OWNER/OPERATOR/VIEWER, ma trận quyền. Người dùng chọn: token **hiện cho ADMIN** khi tạo (ADMIN cấu hình máy chung), **bỏ** nút dừng khẩn cấp của ADMIN, bật LIVE phải được **ADMIN đồng ý**. Thay DEC-15. Thiết kế: `docs/thiet-ke/00-xac-thuc-phan-quyen.md` mục 16 (mục 4, 5, 6, 8, 15 sửa theo).
- **Giữ:** Keycloak (mật khẩu, khóa đăng nhập, thu hồi phiên, mật khẩu tạm), kiến trúc Gateway, Safety/Mode/Risk, pipeline dữ liệu. **Bỏ:** `/api/accounts/{id}/members*`, `POST /api/accounts`, `POST /api/accounts/{id}/gateway/token`, `/api/admin/kill-switch`, `/api/admin/audit`, ADMIN-tự-thành-chủ, enum `Perm`. **Thêm:** migration `0006` (`users.role/status/updated_at`, chỉ thêm cột), `GET /api/admin/users`, `lock`/`unlock`/`reset-password`/cấp lại token, `/api/admin/live-requests` duyệt/từ chối; token sinh trong cùng transaction với USER.
- **Khóa có hiệu lực ở backend, không chỉ giao diện:** phiên (mỗi request), callback đăng nhập, `Guard.check`, ingest (Gateway 403), `allows_new_orders` (False). Không đóng vị thế, không đổi Safety/Mode; mở khóa không tự chạy bot.
- **Lỗi/rủi ro tìm được khi soát:** (1) sau migration, dòng của ADMIN còn ghi `USER` tới lần đăng nhập kế → ADMIN có thể thấy và **tự khóa chính mình** → chặn thao tác lên chính mình + ẩn khỏi danh sách (có test). (2) Bỏ vai trò trung gian có thể vô tình **mở rộng** quyền của dòng VIEWER/OPERATOR cũ → chỉ dòng OWNER có nghĩa (có test). (3) Khóa USER giữ tài khoản nguồn giá làm **cả hệ thống ngừng nhận nến** → hộp thoại khóa cảnh báo rõ (có test). Thử đột biến 12 chốt chặn → cả 12 đều làm test đỏ.
- **Kiểm chứng:** backend 329 passed (gồm test mới cho tạo/khóa/mở khóa/đặt lại mật khẩu/cấp lại token/duyệt LIVE, Keycloak lỗi), ruff sạch; migration 0006 chạy trên PostgreSQL 16 thật với dữ liệu giống máy người dùng (không mất dòng, CHECK chặn giá trị sai, hạ cấp được); frontend 64 passed, tsc/eslint sạch, build OK. **Chưa chạy được ở đây:** `ops/scripts/ci_stack.sh` với Keycloak thật (môi trường này không có Docker daemon) → chờ CI trên GitHub; `e2e_auth.py` đã viết lại theo luồng mới.
- **Giới hạn còn lại:** ADMIN thấy token và mật khẩu tạm của USER (một lần) nên về lý thuyết đăng nhập thay được USER (đánh đổi người dùng chọn; có audit). Chưa có xóa người dùng trên Dashboard. Tài khoản `u-*` chưa ghi nến dùng chung (MT-05, GĐ1).
- **Máy người dùng cần:** build lại `backend frontend` (migration 0006 tự chạy), đăng nhập lại `admin` → trang Quản trị.

