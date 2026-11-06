# CHECKLIST — Gold Trading AI

> **Dành cho AI và người phát triển.** Bản đồ việc theo **giai đoạn tuần tự**, bám theo mô hình
> (`docs/mo-hinh/gold-bot-1-tong-the.png`, `docs/mo-hinh/gold-bot-2-market-intelligence.png`) và đặc tả `docs/huong-dan-chuc-nang/01–12`.
> Trạng thái chi tiết, nhật ký, lý do quyết định: `PROGRESS.md`. Hai file mâu thuẫn thì kiểm tra code rồi sửa cả hai.
>
> **Cập nhật lần cuối:** 2026-11-06 · **Giai đoạn hiện tại: GĐ0 (hoàn thiện nền móng) → GĐ1 (Dữ liệu vào)**

## Nguyên tắc "đi sạch từng giai đoạn" (người dùng chốt 2026-11-06)

1. Làm **hết** một giai đoạn rồi mới sang giai đoạn sau. Giai đoạn có nhiều phần (1A, 1B, …) thì xong **tất cả** các phần.
2. Mỗi giai đoạn làm **đủ mọi nguồn/thành phần mà mô hình yêu cầu**, không chỉ lấy một cái để thử.
3. Mỗi giai đoạn có **bảng case** (tình huống có thể xảy ra, kể cả xấu). Mỗi case phải có **test** và **hành vi mặc định an toàn**.
4. Chỉ qua giai đoạn khi đạt hết **Điều kiện qua giai đoạn (Gate)**, có kiểm chứng trên máy người dùng nếu Gate yêu cầu, và người dùng xác nhận.
5. Việc mà người dùng **chủ động hoãn** được ghi `(hoãn)` và không chặn Gate. Chỉ người dùng mới được hoãn.
6. Trong lúc làm phát hiện case mới → thêm vào bảng case của giai đoạn đó trước khi đóng giai đoạn.
7. **Bảo mật và phân quyền làm ngay trong GĐ0** (người dùng chốt 2026-11-06, đổi quyết định trước đó): đăng nhập bằng **Keycloak**, phân quyền theo vai trò, nền móng đa người dùng (phần **MT**: các việc ghi "GĐ0" làm ngay, phần còn lại làm trong giai đoạn tương ứng). Prompt thực hiện: `docs/prompts/GD0-hoan-thien-nen-mong.md`.

## Cách đọc và cập nhật

**Trạng thái:** `[x]` xong (có test, đã kiểm chứng) · `[~]` có một phần · `[ ]` chưa làm · `[!]` chờ người dùng (quyết định/thao tác)

**Mã việc:** `<KHỐI>-<số>` (ví dụ `ING-09`). **Mã case:** `<giai đoạn><phần>-C<số>` (ví dụ `1A-C07`). **Mã quyết định:** `DEC-<số>`.
Mã **không bao giờ đổi hoặc dùng lại**; việc mới lấy số kế tiếp của khối. Việc bị bỏ giữ dòng, ghi `(bỏ: lý do)`.

**Khi làm một việc:** đọc `CLAUDE.md` + đặc tả tương ứng → làm **một** mã việc, có test cho các case liên quan → kiểm chứng bằng kịch bản riêng → đổi trạng thái ở đây, ghi nhật ký `PROGRESS.md`, commit có mã việc (`ING-09: ...`), push `develop`. Thay đổi ảnh hưởng quyết định giao dịch phải ghi lý do ở `docs/thiet-ke/`.

**Bất biến toàn hệ thống:** point-in-time (`available_at <= decisionAt`), UTC, idempotent, append-only, LIVE khóa mặc định, Safety + Guardian chặn cao nhất, không `MarketView` hợp lệ → không tín hiệu, không phê duyệt Risk → không gửi lệnh, dữ liệu `SAMPLE` không bao giờ dẫn tới SHADOW/LIVE, thiếu dữ liệu → "không đủ dữ liệu" (không đoán, không nội suy), không gọi là "xác suất" khi chưa hiệu chỉnh.

## Lộ trình giai đoạn (theo luồng của mô hình)

| GĐ | Tên | Khối mô hình | Đặc tả | Trạng thái |
| --- | --- | --- | --- | --- |
| 0 | Nền móng: contract, DB, Docker, CI, bảo mật, sao lưu | Database, Vận hành | 01, 12 | `[~]` |
| 1 | **Dữ liệu vào: đủ 4 nhóm nguồn** + lịch thị trường | Nguồn dữ liệu, Ingestion | 02 | `[~]` (mới có giá M15) |
| 2 | Event Orchestrator + Làn nhanh | Event Orchestrator, Làn nhanh | 03 | `[~]` |
| 3 | **6 analyst** (bản luật, chưa ML) | Market Intelligence | 04 | `[~]` (Technical) |
| 4 | Snapshot → Quality Gate → Fusion → MarketView | Market Intelligence | 05 | `[~]` |
| 5 | **Kế hoạch giao dịch:** hồ sơ rủi ro + chiến lược + Risk Engine + Ledger | Strategy, Risk Engine, Risk ledger | 06, 07 | `[~]` |
| 6 | Backtest có chi phí thật | Backtest | 12 | `[ ]` |
| 7 | Training + AI Service + kiểm soát mô hình (ML) | Training, AI Service | 05, 11 | `[ ]` |
| 8 | Paper trading: giả lập khớp lệnh bằng giá sống, Safety tự động, quản lý vị thế, hiệu suất | Safety, Execution, Position Manager, Performance | 08, 09, 10 | `[ ]` |
| 9 | Kết nối lệnh MT5 **demo**: đặt lệnh, đối soát, Guardian EA | Execution, MT5 Gateway, MT5 + Guardian EA | 09 | `[ ]` |
| 10 | SHADOW → LIVE (canary nhỏ) | Mode manager | 12 | `[ ]` |

Dashboard và vận hành của từng thành phần được làm **trong giai đoạn của thành phần đó**, không dồn về cuối.

---

## GĐ0 — Nền móng

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
| DB-09 | Sao lưu & khôi phục DB: script + lịch tự động + **diễn tập khôi phục** | `[ ]` | Giữ ≥ 7 bản; hướng dẫn trong `deploy/README.md` |
| MOD-01 | Mode Manager: LIVE khóa, approver khác actor, đủ `LIVE_CHECKLIST` | `[x]` | `modes/manager.py` |
| MOD-02 | Chặn SHADOW/LIVE khi dùng SAMPLE | `[x]` | `api/app.py` (`mode_guard`) |
| SAF-01 | Safety: ACTIVE/PAUSED/HALTED, ghi trước khi đổi | `[x]` | `safety/supervisor.py` |
| SAF-02 | Safety lưu bền + khôi phục | `[x]` | `storage/repository.py` |
| SAF-03 | Kill switch trên Dashboard, có xác nhận + audit | `[x]` | `POST /api/safety` |
| DSH-01 | Theme AurumDesk, i18n, responsive. **Chỉ web** (không app mobile/PWA) | `[x]` | `frontend/` |
| DSH-02 | Trang Tổng quan | `[x]` | `frontend/src/pages/` |
| OPS-01 | Docker compose db + backend + frontend, migration tự chạy | `[x]` | `docker-compose.yml`, `deploy/` |
| OPS-02 | Bản deploy build thẳng từ GitHub | `[x]` | `deploy/README.md` |
| OPS-03 | Truy cập qua Tailscale (`DASHBOARD_BIND`), mặc định localhost | `[x]` | Không dùng `0.0.0.0` |
| OPS-04 | Cấu hình qua `.env` (`GT_DATA_SOURCE`, `GT_INGEST_TOKEN`, `GT_BROKER_SESSIONS`, `GT_BROKER_SERVER_TZ`) | `[x]` | |
| OPS-05 | CI GitHub Actions (backend, gateway, frontend, lệch contract, build Docker) | `[x]` | `.github/workflows/ci.yml` — 4/4 xanh |
| OPS-06 | CD tự deploy lên máy Windows | `[!]` | **(hoãn — người dùng)**. Thiết kế đã chốt, xem `PROGRESS.md` 2026-11-06 |
| OPS-07 | Đăng nhập Dashboard + API bằng **Keycloak (OIDC)**: backend làm BFF (Authorization Code + PKCE, client confidential), trình duyệt chỉ giữ cookie phiên `HttpOnly; Secure; SameSite=Strict`, không giữ token; mọi API bắt buộc đăng nhập trừ `/api/health` và cổng ingest (token riêng); actor trong audit lấy từ phiên, không lấy từ request | `[x]` | `auth/` (config, oidc, sessions, web). Phiên trong bộ nhớ, cookie `__Host-gt_session`, làm mới mỗi 60 s, kiểm Origin/Host. Test: `tests/test_auth.py` (Keycloak giả, JWKS cục bộ) |
| OPS-14 | Keycloak trong docker compose: phiên bản ghim cụ thể, realm + client nhập từ file JSON trong repo (không chứa bí mật), DB riêng, chạy sau reverse proxy cùng origin, sao lưu cùng DB-09 | `[~]` | Keycloak 26.8.2 (`ops/keycloak/`), DB riêng `keycloak-db` (postgres 16.14), nginx `/auth/`, brute force bật, `check_realm.py` trong CI, `sync-client.sh`. Đã chạy thật: realm nhập đúng, secret khớp `.env`. Còn: sao lưu (DB-09) |
| OPS-15 | **Lối dừng khẩn cấp khi Keycloak hỏng:** lệnh CLI trong container backend chỉ cho phép HALT (không cho ACTIVE/LIVE), có audit `actor=break-glass` | `[x]` | `gt-break-glass status|halt --account X|--all` (`safety/break_glass.py`): chỉ HALT, ghi thẳng DB, `actor=break-glass`; backend nhận trong ~2 s. Test quét AST: không resume/mode/ACTIVE |
| OPS-16 | HTTPS cho truy cập từ máy khác qua **Tailscale Serve** (tên `*.ts.net`), cookie `Secure`, redirect URI đúng; `localhost` dùng cho phát triển | `[ ]` | Thay cho `DASHBOARD_BIND=<IP Tailscale>` |
| OPS-17 | **Phân quyền (RBAC):** vai trò hệ thống `ADMIN` (realm role Keycloak) + vai trò theo tài khoản giao dịch `OWNER`/`OPERATOR`/`VIEWER` (lưu trong DB ứng dụng, khóa theo `sub`); ma trận quyền ghi ở `docs/thiet-ke/`; kiểm quyền ở backend mỗi request | `[x]` | Ma trận quyền: `accounts/access.py` (test so khớp bảng trong `docs/thiet-ke/00-xac-thuc-phan-quyen.md`), kiểm ở `api/accounts.py` mỗi request. LIVE hai bước (yêu cầu + người khác duyệt) |
| OPS-11 | Log có cấu trúc, xoay vòng log, không ghi token/mật khẩu vào log | `[ ]` | |
| OPS-12 | Kiểm tra đồng hồ máy chủ (NTP): lệch > 2 giây → cảnh báo; > 30 giây → chặn nạp realtime | `[ ]` | `ingested_at` dùng đồng hồ backend nên đồng hồ sai = point-in-time sai |
| GW-05 | Đổi token ingest (token cũ đã lộ trong chat) | `[x]` | Người dùng đã đổi trên máy Windows (xác nhận 2026-11-06), không cần hỏi lại. Token theo từng tài khoản, lưu băm, xoay từ giao diện là việc MT-04 |

**Case GĐ0**

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 0-C01 | Backend khởi động lại khi đang ACTIVE | Về PAUSED, ghi `STARTUP_REQUIRES_REVIEW` | `[x]` |
| 0-C02 | Khởi động lại khi đang LIVE | Về PAPER, ghi audit | `[x]` |
| 0-C03 | UPDATE/DELETE trực tiếp vào bảng append-only | DB chặn | `[x]` |
| 0-C04 | Mất volume DB / ổ đĩa hỏng | Khôi phục từ bản sao lưu gần nhất theo hướng dẫn; Safety giữ PAUSED | `[ ]` |
| 0-C05 | Ổ đĩa đầy | Cảnh báo trước ở 85%; khi đầy, ingest báo lỗi rõ, không mất dữ liệu đã ghi | `[ ]` |
| 0-C06 | Thiếu `GT_INGEST_TOKEN` hoặc token < 24 ký tự | Cổng ingest tắt (503) | `[x]` |
| 0-C07 | Cấu hình `.env` sai cú pháp (lịch broker, múi giờ) | Backend không khởi động, báo lỗi rõ | `[x]` |
| 0-C08 | Truy cập không đăng nhập / sai mật khẩu nhiều lần | 401 + chuyển tới đăng nhập; Keycloak khóa tạm (brute force detection); audit | `[~]` 401: `test_every_non_public_route_requires_session`. Còn: brute force trên Keycloak thật (e2e) |
| 0-C11 | Keycloak chết / không truy cập được | Không đăng nhập mới được; phiên đang có chạy tới hết hạn; **HALT vẫn làm được qua OPS-15**; Safety không bao giờ tự sang ACTIVE | `[x]` `tests/test_break_glass.py::test_halt_works_while_keycloak_is_down_and_running_app_sees_it`, `test_auth.py::test_keycloak_down_keeps_existing_session_until_expiry` |
| 0-C12 | Phiên hết hạn / làm mới thất bại / người dùng bị vô hiệu hóa trên Keycloak | 401, đăng nhập lại; người bị vô hiệu không thao tác được nữa | `[x]` `test_disabled_user_loses_access_at_next_refresh`, `test_idle_timeout_and_max_lifetime` |
| 0-C13 | Bị thu hồi vai trò khi đang đăng nhập | Request sau bị 403 ngay (quyền kiểm ở DB mỗi request) | `[x]` `tests/test_rbac.py`: `test_role_revocation_takes_effect_on_next_request` |
| 0-C14 | Request từ trang web khác (CSRF), Origin lạ, DNS rebinding | Từ chối (SameSite=Strict + kiểm Origin/Host) | `[x]` `test_write_from_other_origin_is_blocked_and_audited`, `test_unknown_host_rejected_dns_rebinding`, `test_callback_without_login_cookie_is_rejected` |
| 0-C15 | `VIEWER` gọi API ghi (Safety/Mode) | 403 + audit lần bị từ chối | `[x]` `tests/test_rbac.py`: `test_viewer_write_is_forbidden_and_audited` |
| 0-C16 | Mở khóa LIVE: người duyệt trùng người yêu cầu hoặc không đủ quyền | Từ chối (dựa trên danh tính đã xác thực, không dựa vào tên gõ tay) | `[x]` `tests/test_rbac.py`: `test_live_request_same_person_cannot_approve, test_live_approval_rules` |
| 0-C17 | Đồng hồ lệch làm JWT bị coi là hết hạn/chưa hiệu lực | Cho lệch tối đa vài giây; quá thì từ chối + cảnh báo (liên quan OPS-12) | `[x]` `test_clock_skew_within_leeway_accepted_beyond_rejected` (lệch ≤ 5 s) |
| 0-C18 | Token/mật khẩu xuất hiện trong log | Không bao giờ: test quét log | `[ ]` |
| 0-C09 | Đồng hồ máy lệch | Cảnh báo / chặn nạp realtime (OPS-12) | `[ ]` |
| 0-C10 | CI đỏ | Không deploy (khi có CD) | `[x]` (CI) |

**Gate GĐ0:** OPS-07, OPS-11, OPS-12, OPS-14..17, DB-09 và các việc MT ghi "GĐ0" xong; mọi case 0-C01..C18 và MT-C01..C04, MT-C06 có test; người dùng đã đăng nhập bằng Keycloak qua HTTPS trên máy Windows và điện thoại, diễn tập HALT khi Keycloak tắt, diễn tập khôi phục DB (gồm DB Keycloak). OPS-06 (CD) vẫn hoãn, không chặn Gate.

---

## GĐ1 — Dữ liệu vào (đặc tả 02): đủ 4 nhóm nguồn của mô hình

Mô hình yêu cầu: **Giá MT5** (OHLC, tick) · **Tin tức** (báo, RSS, Fed) · **Lịch kinh tế** (số liệu công bố) · **Vĩ mô, vị thế** (DXY, TIPS, COT).

### Quyết định cần người dùng chốt trước khi làm GĐ1

| Mã | Câu hỏi | Gợi ý (phải xác minh giấy phép/điều khoản trước khi dùng) | TT |
| --- | --- | --- | --- |
| DEC-01 | Nguồn **lịch kinh tế**, đặc biệt **số dự báo (forecast/consensus)** | Lịch + số actual có ở nguồn chính thức miễn phí (BLS, BEA, Fed). Số **dự báo** thường phải trả phí hoặc lấy từ trang web có điều khoản hạn chế. Nếu không có forecast thì `EVT-03` (bất ngờ so với dự báo) phải ghi "không đủ dữ liệu" | `[!]` |
| DEC-02 | Nguồn **tin tức** | Miễn phí: thông cáo chính thức (Fed, Bộ Tài chính, BLS) qua RSS. Tin tổng hợp thời gian thực (Reuters, Bloomberg…) thường trả phí | `[!]` |
| DEC-03 | Nguồn **DXY** | (a) Symbol chỉ số USD trên MT5 nếu broker có; (b) chỉ số USD rộng hằng ngày từ FRED (khác DXY, cần ghi rõ); (c) nguồn có phí | `[!]` |
| DEC-04 | Nguồn **kỳ vọng lãi suất Fed** | Công cụ FedWatch không có API miễn phí; thay thế: lợi suất 2 năm (FRED) làm proxy, ghi rõ là proxy | `[!]` |
| DEC-05 | Nguồn **NHTW mua vàng / dòng tiền ETF** | Dữ liệu NHTW thường theo tháng/quý, trễ lớn; ETF: dữ liệu nắm giữ công bố hằng ngày của quỹ | `[!]` |
| DEC-06 | Ngân sách: chấp nhận nguồn trả phí không, tối đa bao nhiêu/tháng | | `[!]` |
| DEC-07 | Đăng ký khóa API miễn phí (ví dụ FRED) — người dùng tự đăng ký, khóa để trong `.env`, không gửi qua chat | | `[!]` |

### 1A — Giá MT5 (OHLC, tick, spread, thông tin symbol/tài khoản)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-01 | Cửa nạp nến chung: kiểm tra, khử trùng, revision, cờ chất lượng, quarantine, payload gốc | `[x]` | `ingestion/candles.py` |
| ING-02 | Point-in-time cho nến (`available_at`; backfill = `close_time` + cờ `BACKFILL`) | `[x]` | `storage/candles.py` |
| ING-03 | Trùng mâu thuẫn trong cùng batch → cách ly `CONFLICTING_DUPLICATE` | `[x]` | |
| ING-04 | Nguồn dữ liệu mẫu tất định (luôn gắn nhãn SAMPLE) | `[x]` | `ingestion/sources/sample.py` |
| ING-05 | Nguồn CSV + CLI `import-csv` (bắt buộc `--server-tz`) | `[x]` | `ingestion/sources/csv_file.py`, `ingestion/cli.py` |
| ING-06 | R1 kiểm tra múi giờ (> 1% nến ngoài giờ → từ chối cả lô) | `[x]` | `csv_file.check_sessions` |
| ING-07 | Cổng nhận nến từ Gateway (token, dry_run, ≤ 2.000 nến, đồng hồ backend) | `[x]` | `api/ingest.py` |
| GW-01 | Gateway chỉ đọc, test quét mã nguồn chặn hàm giao dịch | `[x]` | `mt5_gateway/` — **không thêm đặt lệnh vào package này** |
| GW-02 | Quy đổi giờ server IANA → UTC, chỉ nến đã đóng | `[x]` | `timeconv.py`, `reader.py` |
| GW-03 | `check` 9 bước, `run` nạp bù + 5 giây/lần, backoff, heartbeat | `[x]` | |
| GW-04 | Chạy thật với MetaQuotes-Demo XAUUSD M15 | `[x]` | 9/9, 5.000 nến, tự kết nối lại |
| ING-14 | Khung **H1, H4, D1** (cho Regime và bối cảnh khung lớn), căn theo giờ server broker | `[ ]` | Hiện chỉ M15. Kiểm tra căn nến D1/H4 theo giờ server, không tự tổng hợp sai từ M15 |
| GW-08 | Gateway gửi **tick/bid/ask/spread sống** (vẫn chỉ đọc) | `[ ]` | |
| ING-08 | Nạp và lưu tick/bid/ask/spread point-in-time | `[ ]` | Lưu gọn (lấy mẫu hoặc tổng hợp theo giây), có chính sách giữ dữ liệu |
| GW-09 | Gateway đọc thông tin tài khoản (equity, margin, đòn bẩy) và symbol (stops level, freeze level, swap, commission nếu có) | `[ ]` | Vẫn chỉ đọc; dùng cho GĐ5 và đối soát GĐ9 |
| GW-06 | Gateway chạy như dịch vụ Windows, tự khởi động cùng máy | `[ ]` | Đóng gói `.exe` build trên runner Windows |
| GW-07 | Hàng đợi bền vững trên đĩa + tự nạp bù khi gián đoạn dài | `[ ]` | Hiện gián đoạn > 5 giờ phải chạy lại `run` |
| ING-15 | Nhận diện **đổi tài khoản / đổi broker / đổi symbol** → tách nguồn dữ liệu, không trộn | `[ ]` | Khóa nguồn theo (server, symbol); đổi thì cần xác nhận người dùng |
| ING-16 | Phát hiện lệch đồng hồ Gateway ↔ backend ↔ server MT5 | `[ ]` | Liên quan OPS-12 |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1A-C01 | Nến chưa đóng / thời gian ở tương lai | Cách ly `BAR_NOT_CLOSED` | `[x]` |
| 1A-C02 | Nến trùng giống hệt / khác giá (khác batch / cùng batch) | Bỏ qua / revision mới / cách ly `CONFLICTING_DUPLICATE` | `[x]` |
| 1A-C03 | OHLC sai (high < low, giá ≤ 0, NaN/Inf, volume âm, thời gian không tz, lệch khung) | Cách ly với lý do cụ thể | `[x]` |
| 1A-C04 | Spike (nến/khoảng nhảy > 8× trung vị) | Gắn cờ, hạ độ tin cậy, không tạo S/R | `[x]` |
| 1A-C05 | Feed đóng băng (≥ 4 nến giống hệt) | `FROZEN_FEED`, analyst STALE | `[x]` |
| 1A-C06 | Thiếu nến giữa phiên | R2 chặn nếu độ phủ < 99% | `[x]` |
| 1A-C07 | Tuần lệch DST châu Âu/Mỹ; giờ mơ hồ/không tồn tại ở giờ server | Quy đổi đúng / bỏ nến mơ hồ, không đoán | `[x]` |
| 1A-C08 | Broker đổi múi giờ server (khác `GT_SERVER_TZ`) khi đang chạy | Phát hiện qua tick sống định kỳ (không chỉ lúc `check`) → dừng gửi + cảnh báo | `[~]` (chỉ kiểm lúc khởi động) |
| 1A-C09 | Gateway tắt lâu (> 5 giờ, > 5.000 nến) | Tự nạp bù toàn bộ khoảng thiếu khi chạy lại; vẫn thiếu → báo rõ | `[~]` |
| 1A-C10 | MT5 mất kết nối / terminal tắt / đăng xuất | Heartbeat STALE sau 30 giây, Dashboard báo mất kết nối, analyst STALE | `[~]` (chưa có trigger Safety — GĐ8) |
| 1A-C11 | Đổi tài khoản demo → thật, hoặc đổi broker | Tách nguồn, không trộn; tài khoản thật → cảnh báo rõ | `[~]` (có cảnh báo REAL, chưa tách nguồn) |
| 1A-C12 | Symbol tên khác (`XAUUSDm`, `XAUUSD.r`) | Cấu hình `GT_BROKER_SYMBOL`, lưu chuẩn thành `XAUUSD` | `[x]` |
| 1A-C13 | Tick đảo thứ tự / trùng / bid > ask / spread âm | Bỏ tick lỗi + đếm, không đổi thứ tự lịch sử | `[ ]` |
| 1A-C14 | Spread giãn lúc rollover (đầu phiên) hoặc ra tin | Gắn cờ `WIDE_SPREAD`; lưu đúng giá trị thật | `[~]` (R5 trên nến) |
| 1A-C15 | Tick vẫn tới khi lịch nói đóng cửa | Lưu kèm cờ, không tính là thị trường mở; nhiều lần → `CALENDAR_MISMATCH` | `[ ]` |
| 1A-C16 | Dữ liệu tới muộn (sau khi analyst đã chạy) | Lưu với `available_at` thật, không viết lại quá khứ | `[x]` |
| 1A-C17 | Backend khởi động lại giữa lúc nạp batch | Gửi lại không nhân đôi | `[x]` |
| 1A-C18 | Token sai/thiếu, batch quá lớn, symbol/khung không đúng | 401 / 413-422 / từ chối, ghi lại | `[x]` |
| 1A-C19 | Nến D1/H4 căn theo giờ server khác nửa đêm UTC | Lưu đúng `open_time` theo broker, không tự cắt lại | `[ ]` |
| 1A-C20 | Đồng hồ máy chạy Gateway lệch | Backend dùng đồng hồ của mình; lệch lớn → cảnh báo | `[~]` |

### 1B — Lịch thị trường và ngày lễ

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| CAL-01 | Lịch tham chiếu New York (CN 18:00 → T6 17:00, nghỉ 17:00–18:00) | `[x]` | `market/hours.py` |
| CAL-02 | Lịch broker (giờ server) giao lịch tham chiếu | `[x]` | `BrokerSessions`, `MarketCalendar` |
| CAL-03 | Bảng **ngày lễ / đóng sớm** có phiên bản (Mỹ: năm mới, MLK, Presidents, Good Friday, Memorial, Juneteenth, Independence, Labor, Thanksgiving, Giáng sinh) | `[ ]` | Ghi rõ nguồn; đối chiếu dữ liệu thật để phát hiện sai (`CALENDAR_MISMATCH`) |
| CAL-04 | Dùng `MarketCalendar` cho cờ `GAP` lúc nạp và R1 | `[ ]` | |
| CAL-05 | Thông báo đổi giờ giao dịch đặc biệt của broker (cập nhật tay, có phiên bản) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1B-C01 | Ngày lễ đóng sớm (ví dụ Labor Day 07/09/2026 thiếu 10 nến) | Không coi là thiếu nến; phân tích không bị chặn oan | `[ ]` |
| 1B-C02 | Ngày lễ rơi vào cuối tuần, nghỉ bù | Theo bảng ngày lễ của năm đó | `[ ]` |
| 1B-C03 | Broker mở/đóng khác bảng ngày lễ | `CALENDAR_MISMATCH` hoặc R2 chặn, cảnh báo cập nhật bảng | `[ ]` |
| 1B-C04 | Giáng sinh – năm mới (nhiều ngày thanh khoản thấp) | Đúng lịch; gắn cờ thanh khoản thấp | `[ ]` |

### 1C — Lịch kinh tế (← DEC-01)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| DB-08 | Bảng lịch kinh tế / tin tức / series vĩ mô (append-only, point-in-time) | `[ ]` | Migration mới |
| ING-09 | Nạp **lịch công bố** (CPI, NFP, FOMC, PCE, GDP, PPI, bán lẻ, thất nghiệp hằng tuần…) cho vài tháng tới | `[ ]` | `releaseAt` theo UTC, giữ múi giờ gốc |
| ING-17 | Nạp **số actual** ngay khi công bố, đo độ trễ | `[ ]` | |
| ING-18 | Nạp **forecast/consensus** và **previous** | `[!]` | ← DEC-01 |
| ING-19 | Ghi nhận **sửa số kỳ trước** (revision) | `[ ]` | Không viết lại quá khứ |
| ING-20 | Mức quan trọng sự kiện có phiên bản (cao/trung/thấp) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1C-C01 | Chưa công bố vs actual = 0 | Hai trạng thái khác nhau, không nhầm | `[ ]` |
| 1C-C02 | Công bố bị **hoãn/hủy** (ví dụ chính phủ Mỹ đóng cửa) | Cập nhật lịch, ghi lịch sử thay đổi; cửa sổ rủi ro theo giờ mới | `[ ]` |
| 1C-C03 | Đổi giờ công bố / hai sự kiện cùng giờ | Đúng giờ mới; gộp cửa sổ rủi ro | `[ ]` |
| 1C-C04 | Giờ công bố qua DST Mỹ | Quy đổi đúng từ giờ ET | `[ ]` |
| 1C-C05 | Nguồn chết đúng lúc công bố | Coi là "chưa biết", **kéo dài** cửa sổ chặn, cảnh báo | `[ ]` |
| 1C-C06 | Hai nguồn lệch nhau / sự kiện bị trùng | Khử trùng theo khóa; lệch → cờ, dùng nguồn chính | `[ ]` |
| 1C-C07 | Không có forecast | Ghi "không đủ dữ liệu" cho phần bất ngờ, vẫn tạo cửa sổ rủi ro | `[ ]` |
| 1C-C08 | Số sửa đổi kỳ trước lớn | Lưu revision, có thể gắn cờ | `[ ]` |

### 1D — Tin tức (← DEC-02)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-10 | Khung nạp tin: khử trùng theo fingerprint, `publishedAt` + `ingestedAt` + URL + nội dung gốc | `[ ]` | |
| ING-21 | Nguồn chính thức: tuyên bố/biên bản/phát biểu Fed, Bộ Tài chính, BLS | `[ ]` | |
| ING-22 | Nguồn tin tổng hợp | `[!]` | ← DEC-02 |
| ING-23 | Nhận diện ngôn ngữ, thực thể cơ bản (Fed, lạm phát, vàng, USD, địa chính trị) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1D-C01 | Cùng tin từ nhiều nguồn | Một bản ghi gốc + liên kết | `[ ]` |
| 1D-C02 | Bài bị sửa sau khi đăng | Lưu phiên bản mới, giữ bản cũ | `[ ]` |
| 1D-C03 | Thiếu/sai `publishedAt`, sai múi giờ | Dùng `ingestedAt`, gắn cờ | `[ ]` |
| 1D-C04 | Nội dung độc hại (prompt injection), quá dài, rỗng, không phải tiếng Anh | Lưu nguyên văn như dữ liệu, **không bao giờ thực thi**; giới hạn độ dài; gắn cờ | `[ ]` |
| 1D-C05 | Nguồn chết / bị giới hạn tần suất | Trạng thái nguồn STALE/MISSING, backoff | `[ ]` |
| 1D-C06 | Tin cũ được đăng lại | Nhận diện bằng fingerprint, không coi là tin mới | `[ ]` |

### 1E — Vĩ mô (← DEC-03, DEC-04, DEC-07)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-11 | Khung series vĩ mô theo `releaseAt` (point-in-time, revision) | `[ ]` | |
| ING-24 | DXY hoặc chỉ số USD thay thế (ghi rõ đó là gì) | `[!]` | ← DEC-03 |
| ING-25 | Lợi suất thực 10 năm (TIPS) | `[ ]` | Công bố trễ 1 ngày làm việc |
| ING-26 | Lợi suất danh nghĩa 2 năm, 10 năm | `[ ]` | |
| ING-27 | Kỳ vọng lãi suất Fed hoặc proxy | `[!]` | ← DEC-04 |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1E-C01 | Số liệu ngày D công bố ngày D+1 | `available_at` = lúc công bố thật, không dùng sớm | `[ ]` |
| 1E-C02 | Ngày nghỉ không có giá trị / giá trị "." | Không nội suy; để trống + cờ | `[ ]` |
| 1E-C03 | Series bị sửa / đổi tên / ngừng | Lưu revision; ngừng → MISSING + cảnh báo | `[ ]` |
| 1E-C04 | Đổi đơn vị | Kiểm tra khoảng giá trị, sai → cách ly | `[ ]` |
| 1E-C05 | Khóa API hết hạn/sai | Nguồn MISSING, cảnh báo, không lộ khóa trong log | `[ ]` |

### 1F — Vị thế và dòng tiền (← DEC-05)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-12 | COT vàng (dữ liệu chốt thứ Ba, công bố thứ Sáu) | `[ ]` | `available_at` = thời điểm công bố |
| ING-28 | Lượng vàng nắm giữ của ETF vàng lớn | `[ ]` | |
| ING-29 | NHTW mua vàng | `[!]` | ← DEC-05, dữ liệu trễ hàng tháng/quý |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 1F-C01 | Ngày chốt ≠ ngày công bố | Dùng ngày công bố cho point-in-time | `[ ]` |
| 1F-C02 | Công bố trễ (nghỉ lễ, chính phủ đóng cửa) | Nguồn STALE đúng TTL, không dùng số cũ như số mới | `[ ]` |
| 1F-C03 | Sửa số liệu / đổi mã hợp đồng | Revision; đổi mã → cảnh báo | `[ ]` |

### 1G — Chung cho mọi nguồn

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ING-13 | Store point-in-time dùng chung cho nguồn không phải nến | `[~]` | `ingestion/point_in_time.py` (chưa dùng): tái dùng hoặc thay |
| ING-30 | Trạng thái từng nguồn HEALTHY/STALE/MISSING/INVALID với **TTL riêng** từng nguồn | `[ ]` | |
| DSH-09 | Trang **"Nguồn dữ liệu"**: trạng thái, lần nhận cuối, độ trễ, số cách ly của từng nguồn | `[ ]` | |
| ING-31 | Quản lý khóa API (chỉ trong `.env`, không commit, không log) | `[ ]` | |
| ING-32 | Ghi lại giấy phép/điều khoản sử dụng của từng nguồn | `[ ]` | `docs/thiet-ke/` |
| ING-33 | Chính sách giữ dữ liệu + ước tính dung lượng (tick, tin) | `[ ]` | |
| ING-34 | Test replay: nạp lại cùng dữ liệu → cùng kết quả cho mọi nguồn | `[ ]` | |
| DSH-03 | Trang Thị trường (nến, EMA/RSI, S/R, thẻ Technical, chất lượng dữ liệu, trạng thái MT5) | `[x]` | |
| DSH-07 | Hiển thị giá sống bid/ask/spread | `[ ]` | ← GW-08 |

**Gate GĐ1:** mọi việc 1A–1G xong (trừ việc người dùng hoãn); mọi case 1A–1G có test; chạy trên máy người dùng **≥ 5 ngày giao dịch liên tục**, trong đó bắt được **ít nhất một lần công bố lớn** (CPI hoặc NFP) với giờ, actual (và forecast nếu có) đúng; trang Nguồn dữ liệu hiển thị đủ; bản sao lưu có dữ liệu mới.

---

## GĐ2 — Event Orchestrator + Làn nhanh (đặc tả 03)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ORC-01 | Runner tối thiểu (polling 15 giây cho Technical) | `[~]` | `analysts/runner.py` — sẽ được thay |
| ORC-02 | Bảng sự kiện → job đúng mô hình: M15 đóng → Technical → Regime → Fusion; CPI/NFP → làn nhanh + Event + News; DXY/yield → Macro; COT → Positioning; output hết hạn → invalidate MarketView | `[ ]` | `orchestrator/` |
| ORC-03 | `jobKey = eventType + subject + eventVersion + analyzerVersion`, hiệu lực đúng một lần | `[ ]` | |
| ORC-04 | Debounce theo loại/symbol/time bucket, không bỏ sự kiện công bố quan trọng | `[ ]` | |
| ORC-05 | Deadline, retry giới hạn, exponential backoff, dead-letter | `[ ]` | |
| ORC-06 | Ghi `correlationId`, nguyên nhân, phiên bản input/output, trạng thái job | `[ ]` | |
| ORC-07 | Invalidate MarketView khi output hết hạn | `[ ]` | |
| ORC-08 | Lưu job bền vững (restart không mất, không chạy lại job đã xong) | `[ ]` | |
| DSH-08 | Hiển thị trạng thái pipeline/job, dead-letter | `[ ]` | |
| FAST-01 | Làn nhanh kích hoạt khi: CPI/NFP vừa ra, tin nóng cấp cao, spread giãn mạnh, bất ngờ so dự báo | `[ ]` | |
| FAST-02 | Xử lý bằng luật (+ FinBERT nếu có), **không gọi LLM nặng**; ngân sách độ trễ tính bằng giây | `[ ]` | |
| FAST-03 | Kết quả: cập nhật `riskFlags`, chặn lệnh 10–15 phút, giảm confidence, đi thẳng Safety (bỏ qua Fusion) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 2-C01 | Cùng sự kiện tới nhiều lần | Một output | `[ ]` |
| 2-C02 | Sự kiện tới sai thứ tự | Xử lý theo thứ tự nhân quả, ổn định khi replay | `[ ]` |
| 2-C03 | Dồn dập sự kiện | Debounce, không bỏ sự kiện quan trọng | `[ ]` |
| 2-C04 | Analyst lỗi / quá hạn deadline | Retry giới hạn → dead-letter, nguồn coi là MISSING, không dùng output cũ quá hạn | `[ ]` |
| 2-C05 | Restart giữa lúc chạy job | Tiếp tục hoặc chạy lại an toàn, không nhân đôi | `[ ]` |
| 2-C06 | Output hết hạn mà không tính lại được | MarketView bị invalidate → không có tín hiệu | `[ ]` |
| 2-C07 | Sự kiện xảy ra khi thị trường đóng | Vẫn xử lý; cờ áp dụng khi mở cửa | `[ ]` |
| 2-C08 | Hai công bố cùng phút | Một cửa sổ chặn gộp | `[ ]` |
| 2-C09 | Làn nhanh vượt ngân sách độ trễ | Cảnh báo; Safety mặc định chặn tới khi xử lý xong | `[ ]` |

**Gate GĐ2:** replay event log ghi lại từ GĐ1 cho kết quả giống hệt; không nhân đôi output; đo được độ trễ làn nhanh trên một lần công bố CPI/NFP đã ghi, nằm trong ngân sách.

---

## GĐ3 — 6 analyst độc lập (đặc tả 04), bản luật (ML để GĐ7)

Hợp đồng chung (`contracts/analyst.py`): `analystId`, `asOf`, `expiresAt`, `confidence`, `features`, `drivers`, `riskFlags`, `sourceStatus`, `qualityFlags`, `version`. Mỗi analyst có thiết kế riêng ở `docs/thiet-ke/`. **Không có xác suất khi chưa hiệu chỉnh.**

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| ANA-01 | Khung chung: hết hạn, trạng thái nguồn, phiên bản, lưu append-only cho mọi analyst | `[~]` | Có cho Technical (`storage/analyst_outputs.py`) |
| ANA-02 | Thẻ giao diện cho từng analyst | `[~]` | Có cho Technical |
| **Technical** | | | |
| TEC-01 | EMA, RSI Wilder, ATR Wilder (đối chiếu thư viện chuẩn) | `[x]` | `analysts/indicators.py` |
| TEC-02 | Cổng chất lượng R2–R6 + `CALENDAR_MISMATCH` | `[x]` | `market/quality.py` |
| TEC-03 | Xu hướng, cấu trúc, swing, vùng S/R (`technical-1.2.0`) | `[x]` | `docs/thiet-ke/03-technical-analyst.md` |
| TEC-04 | Lưu, API, thẻ giao diện; confidence = chất lượng dữ liệu | `[x]` | |
| TEC-05 | Theo dõi ngưỡng R3/R5 trên dữ liệu thật vài ngày | `[!]` | |
| TEC-06 | Pattern giá/nến | `[ ]` | Không rò rỉ tương lai |
| TEC-07 | `volForecast` bằng luật (ATR/EWMA), ghi rõ không phải mô hình | `[ ]` | |
| TEC-09 | Bối cảnh đa khung (H1/H4/D1) | `[ ]` | ← ING-14 |
| **Event & calendar** | | | |
| EVT-01 | Phân loại FOMC/NFP/CPI…, mức quan trọng (luật cứng, không LLM) | `[ ]` | ← ING-09, ING-20 |
| EVT-02 | Cửa sổ rủi ro trước/sau công bố → cờ `EVENT_WINDOW` (độ dài theo mức quan trọng, có phiên bản) | `[ ]` | |
| EVT-03 | Actual – forecast → hướng bất ngờ, `eventRisk` | `[ ]` | Không có forecast → "không đủ dữ liệu" |
| EVT-04 | Xử lý công bố bị hoãn/hủy/đổi giờ | `[ ]` | |
| **News (LLM)** | | | |
| DEC-08 | Chọn nhà cung cấp LLM + ngân sách | `[!]` | |
| NEWS-01 | Lọc trùng, nhận diện thực thể | `[ ]` | ← ING-10, ING-23 |
| NEWS-02 | Lọc trước (FinBERT hoặc luật) → LLM trích stance, impact, novelty, horizon, `newsShock`, có trích dẫn bài gốc | `[ ]` | |
| NEWS-03 | Giới hạn token/timeout, chống prompt injection, lưu prompt + phiên bản mô hình | `[ ]` | |
| NEWS-04 | LLM lỗi/hết ngân sách → analyst MISSING (không đoán) | `[ ]` | |
| **Macro** | | | |
| MAC-01 | Đồng bộ DXY, lợi suất thực 10Y, kỳ vọng Fed theo thời điểm công bố | `[ ]` | ← ING-24..27 |
| MAC-02 | Thay đổi/độ bất thường, macro bias, cờ stress | `[ ]` | TTL phù hợp tần suất thấp |
| **Positioning & sentiment** | | | |
| POSN-01 | Z-score lịch sử COT, ETF, NHTW | `[ ]` | ← ING-12, ING-28, ING-29 |
| POSN-02 | Crowding risk, giả thuyết contrarian ở cực trị | `[ ]` | COT trễ, không coi là thời gian thực |
| **Regime** | | | |
| REG-01 | Phân loại `TREND/RANGE/RISK_OFF/HIGH_VOL` bằng luật (biến động, độ dốc xu hướng…) | `[ ]` | Bản HMM/classifier ở GĐ7 |
| REG-02 | Trọng số gợi ý cho Fusion, theo dõi chuyển regime | `[ ]` | |

| Mã | Tình huống (áp dụng cho **mọi** analyst) | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 3-C01 | Thiếu input bắt buộc | `sourceStatus=MISSING`, không xuất đặc trưng | `[~]` (Technical) |
| 3-C02 | Input quá cũ | STALE | `[~]` (Technical) |
| 3-C03 | Chưa đủ lịch sử | `INSUFFICIENT_HISTORY` | `[~]` (Technical) |
| 3-C04 | Giá trị cực đoan / spike trong input | Gắn cờ, hạ độ tin cậy | `[~]` (Technical) |
| 3-C05 | Dữ liệu SAMPLE | Cờ `SAMPLE_DATA` | `[~]` (Technical) |
| 3-C06 | Thêm dữ liệu tương lai rồi tính lại tại thời điểm cũ | Kết quả không đổi | `[~]` (Technical 40/40) |
| 3-C07 | Đổi công thức/ngưỡng | Tăng `version`, output cũ giữ nguyên | `[~]` |
| 3-C08 | Các nguồn của một analyst mâu thuẫn nhau | Hạ confidence, ghi driver | `[ ]` |
| 3-C09 | (Event) công bố đúng lúc thị trường đóng / cuối tuần | Cửa sổ áp dụng khi mở cửa | `[ ]` |
| 3-C10 | (News) tin chứa lệnh "bỏ qua hướng dẫn…" | Không làm theo; gắn cờ injection | `[ ]` |

**Gate GĐ3:** đủ 6 analyst có thiết kế + test case + thẻ giao diện; chạy song song trên dữ liệu thật ≥ 5 ngày giao dịch; mỗi output truy được về input.

---

## GĐ4 — Snapshot → Data Quality Gate → Fusion → MarketView (đặc tả 05)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| SNP-01 | Snapshot Builder | `[~]` | `intelligence/snapshot_builder.py` — có code + test, **chưa nối luồng** |
| SNP-02 | Lưu snapshot + manifest input để tái dựng | `[ ]` | |
| DQG-01 | Nguồn bắt buộc/tùy chọn, TTL, `sourceStatus` → `REJECTED`/degrade | `[x]` | `intelligence/quality_gate.py` |
| DQG-02 | Schema, outlier, xung đột timestamp | `[ ]` | |
| DQG-03 | Chính sách degrade có phiên bản + audit lý do | `[ ]` | |
| FUS-01 | Fusion bằng luật → `MarketView`; bất đồng → giảm confidence; không lấy đa số đơn thuần khi nguồn tương quan | `[ ]` | Thiết kế ở `docs/thiet-ke/` |
| MKV-01 | Contract `MarketView` | `[x]` | `contracts/market_view.py` |
| MKV-02 | Lưu, hết hạn, invalidate MarketView | `[ ]` | |
| MKV-03 | Hiển thị MarketView trên Tổng quan | `[~]` | Khung có sẵn |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 4-C01 | Thiếu nguồn bắt buộc | `REJECTED`, không có MarketView | `[x]` (Gate) |
| 4-C02 | Nguồn tùy chọn cũ/mất | Giữ snapshot, gắn cờ, hạ confidence theo chính sách | `[~]` |
| 4-C03 | Các analyst bất đồng mạnh | Giảm confidence; có thể `NEUTRAL` | `[ ]` |
| 4-C04 | Đang trong `EVENT_WINDOW` / làn nhanh bật | `riskFlags` truyền xuống MarketView | `[ ]` |
| 4-C05 | MarketView hết hạn trong lúc đang dùng | Lớp sau kiểm lại `expiresAt`, từ chối | `[ ]` |
| 4-C06 | Input từ SAMPLE | MarketView mang cờ, Risk chặn SHADOW/LIVE | `[ ]` |
| 4-C07 | Timestamp các input xung đột | Gắn cờ / REJECTED theo chính sách | `[ ]` |

**Gate GĐ4:** MarketView sinh liên tục trên dữ liệu thật, invalidate đúng, tái dựng được từ manifest, hiển thị trên Tổng quan.

---

## GĐ5 — Kế hoạch giao dịch: hồ sơ rủi ro + chiến lược + Risk Engine + Ledger (đặc tả 06, 07)

### 5A — Hồ sơ rủi ro (việc ③b)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| DEC-09 | Người dùng trả lời: vốn; mục tiêu 4–5% theo ngày/tuần/tháng; lỗ tối đa mỗi lệnh; ngưỡng dừng ngày/tuần; giữ lệnh trong ngày hay qua đêm; broker, đòn bẩy, phí | `[!]` | |
| DB-07 | Bảng hồ sơ rủi ro có phiên bản | `[ ]` | |
| RPF-01 | Hồ sơ rủi ro có phiên bản (append-only, audit) | `[!]` | ← DEC-09 |
| RPF-02 | Đề xuất SL theo ATR, TP theo R:R, lot theo rủi ro, thời gian giữ lệnh ước tính | `[ ]` | Lot làm tròn **xuống**; < tối thiểu → **không khả thi** |
| RPF-03 | Kết luận khả thi bằng số cụ thể | `[ ]` | Ví dụ: vốn 100$, ATR ~13$, lot 0,01 → SL 1,5 ATR mất ~20% vốn |
| RPF-04 | Nhãn "chỉ minh họa" khi SAMPLE | `[ ]` | |
| RPF-05 | Trang nhập hồ sơ và xem kế hoạch | `[ ]` | Thuộc trang Rủi ro (DSH-05) |

### 5B — Chiến lược (Strategy Engine)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| STR-06 | **Văn bản chiến lược v1** được người dùng duyệt: điều kiện vào/ra, phiên giao dịch, cửa sổ cấm, SL/TP, BE, trailing, time-stop, số lệnh tối đa | `[ ]` | `docs/thiet-ke/` |
| STR-01 | Contract `TradeIntent` (SL/TP đúng chiều lệnh) | `[x]` | `contracts/trade_intent.py` |
| STR-02 | Điều kiện vào: MarketView còn hạn, confidence đạt ngưỡng theo regime, không có riskFlags cấm | `[ ]` | `strategy/` |
| STR-03 | Sinh intent: entry, SL, TP, `riskBudgetRequested`, `expiry`, `idempotencyKey` | `[ ]` | Không tự suy volume cuối |
| STR-04 | Chống intent trùng cho cùng strategy/symbol/horizon | `[ ]` | |
| STR-05 | Audit, gửi Risk, ghi lý do khi bị từ chối | `[ ]` | |

### 5C — Risk Engine

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| CORE-05 | Tiền/PnL dùng `Decimal` | `[ ]` | Bắt buộc trước LED-04 |
| RSK-01 | Kiểm Safety, hết hạn intent/MarketView, riskFlags, spread | `[x]` | `risk/engine.py` |
| RSK-02 | Sizing theo rủi ro, volume step/min/max, hạn mức tổng (giữ `ledger.lock`) | `[x]` | |
| RSK-03 | Margin/đòn bẩy | `[ ]` | ← GW-09 |
| RSK-04 | Exposure ròng/gộp, tập trung | `[ ]` | |
| RSK-05 | Hạn mức ngày/tuần, drawdown, chuỗi thua | `[ ]` | ← RPF-01 |
| RSK-06 | Kết quả `REDUCED`, TTL quyết định, gắn policy version | `[ ]` | |
| RSK-07 | Đọc `EVENT_WINDOW`, `WIDE_SPREAD`, `HIGH_VOLATILITY` từ MarketView thật | `[ ]` | |
| RSK-08 | Stops level / freeze level của broker: SL quá gần → từ chối | `[ ]` | ← GW-09 |
| RSK-09 | Ước tính swap qua đêm (thứ Tư ×3) và commission vào rủi ro | `[ ]` | |

### 5D — Risk Ledger (bản paper)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| LED-01 | Reserve/release append-only trong bộ nhớ, test đồng thời | `[x]` | `risk/ledger.py` |
| DB-06 | Bảng lệnh, deal, vị thế, reservation | `[ ]` | |
| LED-02 | Lưu ledger vào DB (`PortfolioState`, `RiskReservation`) | `[ ]` | |
| LED-04 | Fill/đóng lệnh → exposure và PnL (Decimal) | `[ ]` | |
| LED-05 | Khôi phục sau crash giữa reserve và gửi lệnh | `[ ]` | |
| DSH-05 | Trang Rủi ro (hồ sơ, hạn mức, mức đã dùng) | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 5-C01 | Vốn quá nhỏ: lot tối thiểu vẫn vượt rủi ro cho phép | **Từ chối**, nói rõ số tiền thiếu; không làm tròn lên | `[ ]` |
| 5-C02 | SL quá gần (< spread hoặc < stops level) / quá xa | Từ chối | `[ ]` |
| 5-C03 | Tín hiệu ngược chiều khi đang có lệnh | Theo văn bản chiến lược (không tự đảo lệnh nếu chưa định nghĩa) | `[ ]` |
| 5-C04 | Nhiều tín hiệu liên tiếp / trùng | Chống trùng, giới hạn số lệnh | `[ ]` |
| 5-C05 | Chạm ngưỡng lỗ ngày/tuần | Chặn lệnh mới tới kỳ sau; Safety PAUSED | `[ ]` |
| 5-C06 | Chuỗi thua liên tiếp | Giảm rủi ro hoặc dừng theo chính sách | `[ ]` |
| 5-C07 | Giữ lệnh qua cuối tuần (gap qua SL) | Theo chính sách: cấm hoặc tính rủi ro gap | `[ ]` |
| 5-C08 | Swap qua đêm, thứ Tư ×3 | Tính vào chi phí | `[ ]` |
| 5-C09 | Margin không đủ / đòn bẩy bị broker đổi | Từ chối / giảm khối lượng | `[ ]` |
| 5-C10 | Spread giãn lúc vào / đang trong cửa sổ tin | Từ chối | `[~]` (spread) |
| 5-C11 | Intent hoặc MarketView hết hạn | Từ chối | `[x]` |
| 5-C12 | Hai intent đồng thời tiêu cùng ngân sách | Tổng không vượt hạn mức | `[x]` |
| 5-C13 | Equity đổi giữa lúc tính và lúc duyệt | Tính lại dưới khóa | `[~]` |

**Gate GĐ5:** người dùng duyệt hồ sơ rủi ro (DEC-09) và văn bản chiến lược (STR-06); mọi case có test; báo cáo khả thi trên dữ liệu thật.

---

## GĐ6 — Backtest (đặc tả 12)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| BT-01 | Replay theo `available_at` với snapshot + policy/model version lịch sử | `[ ]` | SAMPLE → "không có giá trị đánh giá" |
| BT-02 | Mô phỏng spread thật, slippage (lớn hơn lúc ra tin), commission/swap, độ trễ, fill một phần, giờ thị trường, margin | `[ ]` | |
| BT-03 | Báo cáo: giả định, khoảng dữ liệu, bias còn lại, kết quả theo regime | `[ ]` | |
| BT-04 | Tiêu chí đạt do người dùng duyệt: walk-forward, out-of-sample, số lệnh tối thiểu, drawdown tối đa | `[ ]` | |
| MOD-03 | Mode BACKTEST nối với backtest | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 6-C01 | Rò rỉ tương lai | Test tự động: thêm dữ liệu tương lai không đổi kết quả quá khứ | `[ ]` |
| 6-C02 | Gap cuối tuần, ngày lễ, tuần lệch DST | Mô phỏng đúng | `[ ]` |
| 6-C03 | Thiếu dữ liệu một đoạn | Không giao dịch trong đoạn thiếu, ghi vào báo cáo | `[ ]` |
| 6-C04 | Quá khớp (quá nhiều tham số / tối ưu trên toàn bộ dữ liệu) | Bắt buộc out-of-sample; cảnh báo | `[ ]` |
| 6-C05 | Kết quả không đạt tiêu chí | Quay lại GĐ5, **không** sang GĐ8 | `[ ]` |

**Gate GĐ6:** báo cáo đạt BT-04 và được người dùng duyệt.

---

## GĐ7 — Training + AI Service + kiểm soát mô hình (đặc tả 05, 11)

Mục tiêu: thêm mô hình (LightGBM `pUp/pDown`, Regime HMM/classifier, Fusion meta-model) **chỉ khi** chúng tốt hơn bản luật sau chi phí. Nếu không tốt hơn, giữ bản luật (người dùng quyết định — DEC-10).

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| DEC-10 | Có làm/giữ mô hình ML không, sau khi so với bản luật | `[!]` | |
| TRN-01 | Dataset point-in-time có phiên bản, nhãn không rò rỉ | `[ ]` | |
| TRN-02 | Train/tune walk-forward | `[ ]` | |
| TRN-03 | Đánh giá cả dự báo và tác động giao dịch sau chi phí | `[ ]` | ← BT |
| TRN-04 | Model registry: code version, data manifest, metrics, giới hạn, người duyệt | `[ ]` | |
| AIS-01 | AI Service phục vụ mô hình đã duyệt | `[ ]` | |
| AIS-02 | Ghi `modelVersion` vào mọi output dùng mô hình | `[ ]` | |
| TEC-08 | LightGBM → `pUp/pDown` (chỉ gọi là xác suất sau hiệu chỉnh) | `[ ]` | |
| REG-03 | Regime bằng HMM/classifier | `[ ]` | |
| FUS-02 | Fusion meta-model | `[ ]` | |
| MQC-01 | Calibration, Brier/log loss, drift PSI, tỷ lệ stale; shadow trước, ngưỡng rollback | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 7-C01 | Mô hình chưa hiệu chỉnh | Không gọi là xác suất, không dùng cho quyết định | `[ ]` |
| 7-C02 | Drift vượt ngưỡng | Cảnh báo, quay về bản luật/phiên bản trước | `[ ]` |
| 7-C03 | Không tái tạo được artifact | Không được phục vụ | `[ ]` |

**Gate GĐ7:** mô hình được duyệt hơn bản luật trên out-of-sample sau chi phí và đã chạy shadow; hoặc người dùng quyết định không dùng ML (DEC-10).

---

## GĐ8 — Paper trading (đặc tả 08, 09, 10): khớp lệnh giả lập bằng giá sống, chưa gửi MT5

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| EXE-01 | Order FSM | `[x]` | `execution/order_fsm.py` |
| EXE-02 | Execution Orchestrator: chỉ nhận intent đã Risk duyệt + Safety cho phép | `[ ]` | Adapter khớp lệnh **giả lập** |
| EXE-03 | Kiểm tra trước gửi: hạn approval, Safety, quote mới, spread, volume step, SL/TP, độ lệch giá so với lúc nến đóng | `[ ]` | ← ING-08 |
| EXE-04 | Command riêng cho sửa SL/TP, hủy, đóng (idempotency key, precondition, audit) | `[ ]` | |
| SAF-04 | Trigger tự động: dữ liệu STALE / mất Gateway | `[ ]` | |
| SAF-05 | Trigger tự động: tin nóng, sự kiện cấp cao | `[ ]` | ← FAST-03, EVT-02 |
| SAF-06 | Trigger tự động: spread bất thường, equity/drawdown | `[ ]` | |
| PSM-01 | Position Manager đề xuất BE, trailing, time-stop, chốt/giảm (qua Risk/Execution/Safety) | `[ ]` | `position/` |
| PSM-02 | Không nới rủi ro; time-stop theo giờ khớp thật; restart không lặp command | `[ ]` | |
| PRF-01 | Performance: PnL, drawdown, hit rate, expectancy, MAE/MFE, chi phí, slippage | `[ ]` | `performance/` |
| PRF-02 | Tách paper/shadow/live, theo strategy/regime; so với backtest | `[ ]` | |
| DSH-04 | Trang Lệnh & vị thế | `[ ]` | |
| DSH-06 | Trang Nhật ký (audit, incident) | `[ ]` | |
| OPS-09 | Thông báo sự cố (mất MT5, giá cũ, Safety tự dừng) | `[ ]` | |
| OPS-08 | Runbook sự cố bản đầu | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 8-C01 | Safety chuyển PAUSED/HALTED khi đang có lệnh | Không lệnh mới; vị thế chỉ thao tác bảo vệ | `[ ]` |
| 8-C02 | Mất Gateway khi đang có vị thế paper | STALE → PAUSED; vị thế giữ, đánh dấu chưa định giá được | `[ ]` |
| 8-C03 | Restart khi đang có vị thế | Khôi phục đúng, không lặp command | `[ ]` |
| 8-C04 | Gap qua SL (cuối tuần/tin) | Khớp ở giá mở cửa thật, không ở giá SL | `[ ]` |
| 8-C05 | Time-stop, trailing, BE | Đúng quy tắc chiến lược | `[ ]` |
| 8-C06 | Command trùng | Idempotent | `[ ]` |

**Gate GĐ8:** paper chạy ≥ 4 tuần (người dùng có thể đổi số tuần) trên dữ liệu thật; chênh lệch so backtest trong ngưỡng đã đặt; không có sự cố chưa xử lý.

---

## GĐ9 — Kết nối lệnh MT5 demo (đặc tả 09)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| GW-10 | **Thành phần đặt lệnh riêng** (gửi/sửa/hủy, map request–ticket, reason code chuẩn, magic number) | `[ ]` | Package mới, tách `mt5_gateway`; review riêng; mTLS/token |
| EXE-05 | `UNKNOWN` → truy vấn MT5 trước, không retry mù | `[ ]` | |
| LED-03 | Đối soát định kỳ order/deal/position/equity/margin với MT5 | `[ ]` | Lệch nghiêm trọng → HALT + incident |
| SAF-07 | Hành động Safety thật: hủy lệnh chờ, giảm/đóng vị thế, xác nhận từ MT5 | `[ ]` | |
| GEA-01 | Bản nháp Guardian EA | `[~]` | `guardian_ea/GuardianEA.mq5` — chưa biên dịch |
| GEA-02 | Biên dịch, test trên MT5 demo | `[ ]` | |
| GEA-03 | Ngưỡng equity cứng; đóng/hạn chế khi backend mất kết nối | `[ ]` | |
| GEA-04 | Diễn tập định kỳ | `[ ]` | |
| GW-11 | Lịch giao dịch tự động từ MT5 (nếu có cách đọc) | `[ ]` | Hiện chép tay |
| OPS-10 | Chaos test: mất mạng, restart, gửi trùng | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 9-C01 | Mất ACK sau khi MT5 đã nhận lệnh | Truy vấn, không tạo lệnh thứ hai | `[ ]` |
| 9-C02 | Requote / market closed / bị từ chối (mã lỗi MT5) | Reason code chuẩn, không retry mù | `[ ]` |
| 9-C03 | Khớp một phần | Ledger cập nhật đúng | `[ ]` |
| 9-C04 | Terminal/Gateway restart giữa lệnh | Đối soát lại trước khi làm tiếp | `[ ]` |
| 9-C05 | **Người dùng tự đặt lệnh tay** trên MT5 | Nhận diện bằng magic number; tính vào exposure; không tự quản lý lệnh lạ | `[ ]` |
| 9-C06 | Ledger lệch MT5 | HALT, khóa lệnh mới, incident | `[ ]` |
| 9-C07 | Backend chết khi đang có vị thế | Guardian EA bảo vệ | `[ ]` |

**Gate GĐ9:** ≥ 2 tuần trên MT5 demo với đối soát sạch; diễn tập kill switch và Guardian đạt.

---

## GĐ10 — SHADOW → LIVE (đặc tả 12)

| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| LIVE-01 | Đủ 7 mục `LIVE_CHECKLIST` (`reconciliation_clean`, `required_sources_healthy`, `kill_switch_tested`, `guardian_ea_tested`, `risk_limits_approved`, `model_versions_approved`, `on_call_ready`) | `[ ]` | `modes/manager.py` |
| LIVE-02 | SHADOW trên tài khoản thật (không gửi lệnh) và so với paper | `[ ]` | |
| LIVE-03 | LIVE canary: khối lượng nhỏ nhất, hạn mức thấp, điều kiện rollback rõ | `[ ]` | |
| OPS-13 | Runbook đầy đủ + người trực + quyền dừng khẩn | `[ ]` | |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 10-C01 | Mở khóa LIVE thiếu mục checklist / cùng một người duyệt | Từ chối | `[x]` |
| 10-C02 | Restart khi đang LIVE | Về PAPER | `[x]` |
| 10-C03 | Vi phạm hạn mức canary | Tự HALT | `[ ]` |

**Gate GĐ10:** người dùng phê duyệt hai bước; mọi mục "Checklist trước LIVE" ở `docs/huong-dan-chuc-nang/12-van-hanh-kiem-thu.md` đạt.

---

## MT — Đa người dùng, mỗi người một tài khoản riêng (để sau)

**Trạng thái: nền móng làm trong GĐ0 (người dùng chốt 2026-11-06).** Mục tiêu: **mỗi người có vốn, MT5, hồ sơ rủi ro, lệnh riêng**. Việc ghi "GĐ0" làm ngay; việc khác làm ở giai đoạn ghi bên cạnh. Chưa nhận người dùng thứ hai trước khi DEC-11, DEC-12 được trả lời.

Ảnh hưởng tới các giai đoạn: dữ liệu thị trường (giá, tin, lịch, vĩ mô) **dùng chung theo nguồn/broker**; còn tài khoản MT5, Gateway + token, hồ sơ rủi ro, chiến lược được bật, Safety, Mode, Ledger, lệnh, vị thế, hiệu suất, audit thì **riêng từng tài khoản**.

| Mã | Câu hỏi cần chốt | TT |
| --- | --- | --- |
| DEC-11 | Người dùng là ai: người thân/bạn bè hay khách hàng bên ngoài? Hệ thống **tự giao dịch tiền của họ** hay chỉ đưa phân tích để họ tự quyết? | `[x]` 2026-11-06: người thân/bạn bè, hệ thống **tự giao dịch** |
| DEC-12 | Rủi ro pháp lý khi quản lý/giao dịch tiền của người khác hoặc cung cấp khuyến nghị đầu tư (cần hỏi luật sư theo nơi cư trú) | `[!]` Chưa trả lời → `GT_MULTI_USER_ENABLED=0`: backend từ chối thêm người thứ hai |
| DEC-13 | Nơi chạy hệ thống: máy của người dùng hiện tại (Tailscale) hay máy chủ riêng; mỗi người tự chạy Gateway trên máy Windows của họ hay gom về một máy | `[x]` 2026-11-06: máy Windows của người dùng, **gom mọi Gateway/MT5 về máy này** (nhiều terminal MT5 trên một máy: GĐ1/MT-05) |
| DEC-14 | Các broker khác nhau → lịch phiên, spread, giá khác nhau: chấp nhận nhiều nguồn giá song song? | `[!]` |

| Mã | Việc | TT | Ghi chú |
| --- | --- | --- | --- |
| MT-01 | Mô hình dữ liệu: `User` (khóa theo `sub` của Keycloak), `TradingAccount` (một tài khoản MT5), vai trò theo tài khoản (`OWNER`/`OPERATOR`/`VIEWER`) + quản trị hệ thống | `[x]` | **GĐ0.** Bảng `users`, `trading_accounts`, `account_members` (migration 0004). ADMIN đầu tiên đăng nhập → OWNER tài khoản `default`. Test: `tests/test_repository_accounts.py` (bộ nhớ + SQLite) |
| MT-02 | Thêm `account_id` vào mọi bảng riêng (Safety, Mode, audit, hồ sơ rủi ro, ledger, lệnh, vị thế, analyst output dùng dữ liệu riêng) bằng migration mới; dữ liệu hiện có gán cho tài khoản đầu tiên | `[x]` | **GĐ0.** `account_id` cho Safety/Mode/audit (+ `actor_sub`), dữ liệu cũ → `default` bằng `ADD COLUMN DEFAULT` (không UPDATE). Đã kiểm trên TimescaleDB thật: trigger append-only còn nguyên, schema khớp migration |
| MT-03 | Mọi API/truy vấn lọc theo tài khoản của người đang đăng nhập (chặn ở tầng truy cập dữ liệu, không chỉ ở giao diện) | `[x]` | **GĐ0.** Mọi API của tài khoản đi qua `Guard.check` (không thành viên → 404, thiếu quyền → 403, có audit). Dữ liệu thị trường dùng chung |
| MT-04 | Token Gateway riêng từng tài khoản; Gateway chỉ ghi được vào tài khoản của mình | `[x]` | **GĐ0.** Token `gtk_…` lưu SHA-256, xoay thu hồi token cũ ngay, `GT_INGEST_TOKEN` cũ chỉ còn cho `default` tới lần xoay đầu; Gateway khai sai `account_id` → 403; chỉ tài khoản `price_feed` ghi nến. Giao diện: trang Tài khoản (hiện token đúng một lần) |
| MT-05 | Nguồn giá theo broker/server (một tài khoản ↔ một nguồn); analyst chạy theo từng nguồn | `[ ]` | **GĐ1.** ← ING-15, DEC-14 |
| MT-06 | Safety và Mode theo từng tài khoản + kill switch toàn hệ thống cho quản trị | `[x]` | **GĐ0.** `accounts/runtime.py`: Safety/Mode riêng từng tài khoản, khôi phục cho mọi tài khoản, DB là nguồn sự thật (ghi có `expected_last`, đồng bộ 2 s), kill switch toàn hệ thống `POST /api/admin/kill-switch` |
| MT-07 | Hồ sơ rủi ro, hạn mức, ledger, đối soát theo từng tài khoản | `[ ]` | **GĐ5.** |
| MT-08 | Duyệt LIVE theo từng tài khoản (approver khác actor, cùng quyền với tài khoản đó) | `[ ]` | **GĐ10.** |
| MT-09 | Dashboard: chọn tài khoản, chỉ thấy tài khoản được cấp quyền | `[x]` | **GĐ0.** Header: người đăng nhập, chọn tài khoản (chỉ tài khoản có quyền), đăng xuất; nút khóa theo `permissions` từ backend; duyệt LIVE; kill switch ADMIN; trang `#account` |
| MT-10 | Quản lý người dùng: mời, khóa, đổi vai trò, có audit | `[x]` | **GĐ0.** `/api/accounts/{id}/members` thêm (username/email của người đã đăng nhập), đổi vai trò, gỡ; không gỡ/hạ OWNER cuối; audit; `GT_MULTI_USER_ENABLED=0` chặn người thứ hai (DEC-12). Test: `tests/test_members.py`. Khóa người dùng toàn hệ thống: vô hiệu hóa trên Keycloak (≤ 60 s) |
| MT-11 | Mã hóa/bảo vệ thông tin tài khoản MT5 và token | `[ ]` | **GĐ0.** |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| MT-C01 | Người A gọi API với id tài khoản của người B | 404/403, ghi audit | `[x]` `tests/test_rbac.py`: `test_user_cannot_see_or_touch_other_account` |
| MT-C02 | Gateway của A gửi dữ liệu kèm tài khoản B | Từ chối | `[x]` `tests/test_gateway_tokens.py::test_gateway_of_a_cannot_write_into_b` |
| MT-C03 | A bấm dừng khẩn cấp | Chỉ tài khoản A dừng; B không bị ảnh hưởng | `[x]` `tests/test_rbac.py`: `test_halt_of_one_account_does_not_affect_other` |
| MT-C04 | Quản trị bấm kill switch toàn hệ thống | Mọi tài khoản HALTED | `[x]` `tests/test_rbac.py`: `test_global_kill_switch_halts_every_account_admin_only` |
| MT-C05 | Hai tài khoản khác broker, giờ phiên khác nhau | Mỗi tài khoản dùng lịch và giá của broker mình | `[ ]` |
| MT-C06 | Người dùng bị khóa khi đang có lệnh mở | Không thao tác được nữa; vị thế vẫn được Safety/Guardian bảo vệ | `[x]` `tests/test_rbac.py`: `test_removed_user_cannot_act_but_safety_state_is_kept` |
| MT-C07 | Lỗi/sự cố ở tài khoản A (ví dụ lệch đối soát) | Chỉ HALT tài khoản A | `[ ]` |

## Phụ lục — Mã cũ đã chuyển chỗ

Không có mã nào bị xóa. `ING-11` (vĩ mô) và `ING-12` (vị thế) nay là khung chung của 1E/1F, chi tiết tách thành `ING-24..29`. `TEC-08`, `FUS-02`, `MQC-01`, `AIS-01..02`, `TRN-01..04` chuyển sang GĐ7. `REG-01` là bản luật; bản ML là `REG-03`.
