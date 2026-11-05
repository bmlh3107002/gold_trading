# Tiến độ dự án — Gold Trading AI

> File này cập nhật sau **mỗi** đợt làm việc. Phiên sau đọc file này trước, không cần đọc lại toàn bộ repo.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`.

**Cập nhật lần cuối:** 2026-11-05 · **Nhánh làm việc:** `develop`

## Quyết định đã chốt

| Chủ đề | Quyết định |
| --- | --- |
| Ngôn ngữ | Python cho backend, AI, MT5 Gateway và backtest (không dùng Java) |
| Giao diện | React 18 + TypeScript + Vite, nằm chung repo (`frontend/`). Theme **AurumDesk** (terminal tối), i18next tiếng Việt, icon Lucide, font Inter tự host |
| Guardian EA | MQL5 |
| Cấu trúc | Monorepo: `backend/`, `mt5_gateway/`, `guardian_ea/`, `frontend/`, `contracts/` |
| Contract | Pydantic ở backend là nguồn sự thật → `contracts/openapi.json` → type TS (`npm run gen:api`) |
| Database | PostgreSQL/TimescaleDB (image `timescale/timescaledb:2.17.2-pg16`), SQLAlchemy 2 Core + psycopg 3, migration bằng Alembic |
| Quản lý Python | `uv` (mỗi package có `uv.lock` riêng) |
| Git | Push lên `develop` (nhánh mặc định trên GitHub). Không tạo PR nếu chưa được yêu cầu |
| Dữ liệu giá | Một cửa nạp `CandleIngestor` cho mọi nguồn (`SAMPLE`/`CSV`/`MT5`). Dashboard đọc **một** nguồn theo `GT_DATA_SOURCE` (mặc định Docker: `SAMPLE`). Về sau MT5 Gateway đẩy dữ liệu qua WebSocket vào cùng cửa nạp |
| Biểu đồ | `lightweight-charts@4.2.1` (Apache-2.0); đã tắt logo nổi, có dòng ghi nguồn kèm link tradingview.com dưới biểu đồ theo yêu cầu giấy phép |
| Chạy trên máy cá nhân | Docker. `deploy/docker-compose.yml` build thẳng từ GitHub, không cần clone. Project `gold_trading`, image `gold_trading/backend` và `gold_trading/frontend`, volume `gold_trading_db_data` |

## Trạng thái theo thành phần

Chú thích: ✅ xong khung có test · 🟡 có một phần · ⬜ chưa làm

| # | Thành phần | Trạng thái | Vị trí | Ghi chú |
| --- | --- | --- | --- | --- |
| — | Data contract | ✅ | `backend/src/gold_trading/contracts/` | Bất biến (`frozen`), `extra=forbid`, datetime bắt buộc có tz → UTC |
| — | Lưu trữ vận hành | ✅ | `backend/src/gold_trading/storage/`, `backend/migrations/` | Bảng append-only `safety_transitions`, `mode_changes`, `audit_log`; trigger DB chặn UPDATE/DELETE |
| 02 | Ingestion nến | ✅ | `ingestion/candles.py`, `ingestion/sources/`, `storage/candles.py`, `migrations/versions/0002_candles.py` | Kiểm tra, khử trùng, revision, cờ chất lượng, quarantine. Hypertable TimescaleDB, append-only. Nguồn: dữ liệu mẫu (`sample.py`, `sample_feed.py`) và CSV (`csv_file.py`, CLI `ingestion/cli.py`). Chưa có: tin tức, lịch kinh tế, vĩ mô, tick |
| 02 | Point-in-time (bản cũ) | 🟡 | `ingestion/point_in_time.py` | Store chung trong bộ nhớ, chưa dùng; nến đã có store riêng |
| — | Lịch thị trường | ✅ | `market/hours.py` | Tham chiếu theo giờ New York: CN 18:00 → T6 17:00, nghỉ 17:00–18:00. **Giao** với giờ báo giá của broker (`GT_BROKER_SESSIONS` + `GT_BROKER_SERVER_TZ`, giờ server, chép tay từ MT5 Specification) cho MT5/CSV. Chưa có ngày lễ |
| — | Chỉ báo | ✅ | `analysts/indicators.py` | EMA (khởi tạo bằng SMA), RSI Wilder; test theo giá trị tham chiếu |
| 03 | Event Orchestrator | ⬜ | `orchestrator/` | |
| 04 | Technical analyst v1 | ✅ | `analysts/technical.py`, `analysts/runner.py`, `market/quality.py`, `storage/analyst_outputs.py`, `migrations/versions/0003_analyst_outputs.py` | Thiết kế: `docs/thiet-ke/03-technical-analyst.md`. Cổng chất lượng R2–R6; ATR/EMA/RSI, xu hướng, swing (xác nhận sau 3 nến), hỗ trợ/kháng cự. **Không có xác suất, không có tín hiệu**; confidence = chất lượng dữ liệu. Chạy mỗi 15s, lưu append-only, idempotent theo hash đầu vào |
| 04 | 5 analyst còn lại | ⬜ | `analysts/` | Thứ tự đã chốt: Event & calendar → Macro → News → Positioning → Regime |
| 05 | Snapshot Builder | ✅ | `intelligence/snapshot_builder.py` | |
| 05 | Data Quality Gate | ✅ | `intelligence/quality_gate.py` | Kiểm tra required/optional, TTL, source_status. Chưa có outlier/schema |
| 05 | Fusion / MarketView | 🟡 | `contracts/market_view.py` | Có contract, chưa có fusion |
| 06 | Strategy Engine | ⬜ | `strategy/` | Có contract `TradeIntent` (validate SL/TP theo chiều lệnh) |
| 07 | Risk Engine | 🟡 | `risk/engine.py` | Có: Safety, hết hạn, risk flags, spread, sizing, hạn mức tổng. Chưa có: margin, correlation, exposure ròng, daily DD |
| 07 | Risk Ledger | 🟡 | `risk/ledger.py` | Reserve/release append-only trong bộ nhớ. Chưa có fill/PnL, chưa đối soát MT5 |
| 08 | Safety Supervisor | ✅ | `safety/supervisor.py` | Chưa nối các trigger tự động (tin nóng, spread, equity) |
| 09 | Order FSM | ✅ | `execution/order_fsm.py` | Chưa có Execution Orchestrator |
| 09 | MT5 Gateway **chỉ đọc** | ✅ | `mt5_gateway/`, `backend/.../api/ingest.py` | Thiết kế: `docs/thiet-ke/09a-mt5-gateway-chi-doc.md`, hướng dẫn: `mt5_gateway/README.md`. Lệnh `check`/`run`; đọc nến M15 đã đóng, quy đổi giờ server (IANA) → UTC; nạp bù 5.000 nến rồi 5 giây/lần; nhịp tim. Backend: `POST /api/ingest/mt5/candles` (token, dry_run, R1), `/heartbeat`, `GET /api/gateway/status`. **Đã chạy với MT5 demo thật** (MetaQuotes-Demo, 2026-11-05): check 9/9, nạp 5.000 nến. Chưa đặt lệnh (cố ý) |
| 09 | Guardian EA | 🟡 | `guardian_ea/GuardianEA.mq5` | **Chưa biên dịch, chưa test** |
| 10 | Position Manager / Performance | ⬜ | `position/`, `performance/` | |
| 11 | Training / registry | ⬜ | | |
| 12 | Mode Manager | ✅ | `modes/manager.py` | LIVE khóa, cần approver khác actor và đủ `LIVE_CHECKLIST` |
| 12 | Dashboard | 🟡 | `frontend/` | Theme AurumDesk. **Tổng quan**: metric, điều khiển Safety/Mode, MarketView, lịch sử. **Thị trường** (`#market`): nến M15 + EMA 20/50 + RSI 14 + đường hỗ trợ/kháng cự (chỉ khi kết quả analyst còn hiệu lực và HEALTHY), legend theo con trỏ, banner dữ liệu mẫu/giá cũ, thẻ Phân tích kỹ thuật, chất lượng dữ liệu. Header: giá, thay đổi 24h, phiên, nhãn "Dữ liệu mẫu". Lệnh, Rủi ro, Nhật ký: "Sắp có" |
| 12 | API | 🟡 | `backend/src/gold_trading/api/app.py` | `/api/health` (kiểm tra DB, 503 nếu lỗi), `/api/status` (có `storage`, `data_source`, `data_is_sample`), `/api/audit`, `/api/market/summary`, `/api/market/candles` (kèm EMA/RSI, warm-up 200 nến), `/api/market/quality`, `/api/analysts/technical/latest`, `POST /api/safety`, `POST /api/mode`. Mọi lệnh ghi đều vào audit, kể cả lệnh bị từ chối. **Chưa có xác thực** |
| 12 | Backtest | ⬜ | | |
| — | Docker | ✅ | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `deploy/` | Một lệnh `docker compose up -d --build` chạy db + backend + frontend. Backend chạy `alembic upgrade head` rồi mới start (`scripts/entrypoint.sh`). DB không mở cổng ra host ở bản `deploy/`. Dashboard ở `127.0.0.1:8080` |

## Lệnh kiểm tra nhanh

```bash
cd backend && uv sync && uv run pytest -q && uv run ruff check .
```

```bash
cd mt5_gateway && uv sync && uv run pytest -q
```

```bash
cd frontend && npm install && npm run check && npm run build
```

`npm run check` = `tsc -b` + `eslint .` + `vitest run`.

Kết quả lần cuối: backend 164 passed, mt5_gateway 26 passed (không sửa), frontend 35 passed + tsc/eslint sạch + build OK, ruff sạch.

## Lưu ý kỹ thuật

- `create_app(repo)` nhận `Repository` (`InMemoryRepository` cho test, `SqlRepository` cho Postgres/SQLite). Không truyền thì đọc `DATABASE_URL`; không có biến này thì dùng bộ nhớ. Chạy bằng `uvicorn --factory gold_trading.api.app:create_app`.
- Quy tắc khôi phục khi khởi động (`storage/repository.py`): ACTIVE → PAUSED (ghi event `STARTUP_REQUIRES_REVIEW`, actor `system`, nguồn `startup`), HALTED giữ nguyên, LIVE → PAPER (ghi audit).
- `SafetySupervisor(persist=...)` và `ModeManager(on_change=...)` ghi **trước** khi đổi state; ghi lỗi thì state giữ nguyên.
- Đổi schema: sửa `storage/schema.py` **và** thêm migration mới trong `backend/migrations/versions/` (không sửa `0001`). Test dùng SQLite với `create_all()`.
- CORS chỉ mở cho `http://localhost:5173`. Vite proxy `/api` sang `localhost:8000`.
- Risk Engine giữ `ledger.lock` khi tính headroom và reserve, để tránh over-allocation khi chạy đồng thời.
- Khi Docker chạy, CORS không cần vì nginx phục vụ dashboard và `/api` cùng origin.
- Backend Dockerfile cài uv bằng pip (không `COPY --from=ghcr.io/...`) để chỉ phụ thuộc Docker Hub và PyPI.
- Khi build Docker trong sandbox cloud: Docker Hub hay trả 429 (dùng `dockerd --registry-mirror=https://mirror.gcr.io`), và cần chèn CA của proxy (`/root/.ccr/ca-bundle.crt`) vào một **bản sao** Dockerfile trong scratchpad. Không commit CA vào repo.
- **MT5 Gateway (chỉ đọc):**
  - Chỉ được gọi các hàm trong `reader.READ_ONLY_FUNCTIONS`. Module MT5 bị bọc bởi `_ReadOnly`; test `test_source_contains_no_trading_calls` quét mã nguồn để tìm hàm giao dịch. **Không thêm chức năng đặt lệnh vào package này**; khi làm execution thì tách thành thành phần riêng, có review riêng.
  - Giờ MT5 = giờ server viết như UTC. Bắt buộc `GT_SERVER_TZ` dạng IANA, không dùng độ lệch cố định. Kiểm tra chéo bằng tick sống (khi có) và R1 trên **toàn bộ** lịch sử.
  - `copy_rates_from_pos(..., start_pos=1, ...)`: vị trí 0 là nến đang chạy.
  - Backend dùng **đồng hồ của backend** làm `ingested_at`. Cổng nhận dữ liệu tắt nếu không có `GT_INGEST_TOKEN` (≥ 24 ký tự).
  - Chạy trên Windows bằng `uv run mt5-gateway check|run` (`.python-version` = 3.12). Cấu hình ở `mt5_gateway/gateway.env`.
- **Lịch thị trường:** mọi chỗ cần biết "nến nào lẽ ra phải có" dùng `MarketCalendar` (`MarketDataService.calendar`), không gọi thẳng `bar_in_session` của lịch tham chiếu. Chưa áp dụng cho cờ `GAP` lúc nạp và R1 (vẫn dùng lịch tham chiếu; lịch broker là tập con nên R1 không bị ảnh hưởng). Cấu hình sai → backend không khởi động.
- **Technical analyst:** đọc `docs/thiet-ke/03-technical-analyst.md` trước khi sửa. Đổi công thức hoặc ngưỡng thì tăng `VERSION` trong `analysts/technical.py`. Frontend đọc `features` qua `lib/technical.ts` (sai kiểu thì trả null, không đoán).
- **Frontend — quy ước theme AurumDesk:**
  - Màu, khoảng cách, font chỉ khai báo trong `frontend/src/styles/tokens.css` (dark mặc định, light qua `html[data-theme="light"]`). Không hardcode màu trong component.
  - CSS: `base.css`, `layout.css` (sidebar 238px, header 66px, breakpoint 1100px/720px/480px), `components.css`.
  - Component dùng chung ở `src/components/ui/`: `Button`, `IconButton`, `Card`, `Badge`, `Field`, `Dialog` (focus trap, Escape), `InfoTip`, `StateView` (Loading/Empty/Error/Skeleton). Layout: `Sidebar`, `Header`, `ConnectionBadge`, `Logo`.
  - Mọi chuỗi giao diện nằm trong `src/i18n/vi.ts` (có type-check key). Enum hiển thị qua `src/lib/labels.ts`; số/tiền/ngày dùng `src/lib/format.ts` (`vi-VN`).
  - Lỗi API được phân loại trong `ApiError.kind` (network/conflict/validation/server). UI chỉ hiện thông báo i18n, không hiện chi tiết thô.
  - Trạng thái kết nối (`src/lib/connection.ts`): connecting/live/stale (>10s)/disconnected. Khi mất kết nối, dữ liệu cũ vẫn giữ và có banner "Dữ liệu đã cũ".
  - Header **không** hiển thị giá giả. Hiện ghi "Chưa có dữ liệu giá" cho tới khi có nguồn giá thật.
  - Theme lưu ở localStorage `aurumdesk.theme`, có try/catch.
- **Dữ liệu nến — quy tắc bắt buộc:**
  - Nến chỉ hợp lệ khi **đã đóng** (`available_at >= close_time`). `ingested_at` = đồng hồ thật lúc nhận. `available_at` = lúc được coi là đã biết: realtime thì bằng `ingested_at`; nạp bù (`backfill=True`) thì bằng `close_time` + cờ `BACKFILL`. Revision luôn có `available_at = ingested_at`.
  - Truy vấn point-in-time lọc theo `available_at`, dùng `store.query(..., as_of=...)`. Không đọc thẳng bảng.
  - Khóa nến: `(symbol, timeframe, source, open_time, revision)`. Cùng giá trị → bỏ qua; khác giá trị → revision mới.
  - Trùng thời điểm trong **cùng một batch** mà giá khác nhau: cách ly tất cả (`CONFLICTING_DUPLICATE`), không tạo revision giả. Giống hệt nhau thì giữ một.
  - Độ mới dữ liệu (`MarketDataService._freshness`): so nến mới nhất với **nến lẽ ra đã đóng gần nhất trong giờ mở cửa** (`expected_last_close`, cho trễ `FRESHNESS_GRACE` = 2 phút). Nhờ vậy không báo nhầm lúc mở cửa đầu tuần, và vẫn báo `STALE` vào cuối tuần nếu nguồn đã chết từ trước khi đóng cửa.
  - R1: CLI nạp CSV **từ chối cả file** nếu > 1% nến (khi có ≥ 200 nến) rơi vào giờ đóng cửa, và gợi ý độ lệch giờ khớp nhất (`csv_file.check_sessions`). Không có cờ bỏ qua.
  - CLI chỉ cho khung M1–H1. H4 trở lên được broker căn theo giờ server, chưa hỗ trợ.
  - CSV từ MT5 dùng giờ server broker. **Bắt buộc `--server-tz`**; giờ mơ hồ do đổi DST bị cách ly, không đoán.
  - Dữ liệu mẫu: tất định theo seed (`20260101`) và giá khởi đầu 2400. `ModeManager(guard=...)` chặn SHADOW/LIVE khi `GT_DATA_SOURCE=SAMPLE`; mode đã lưu là SHADOW/LIVE sẽ về PAPER khi khởi động (ghi audit).
  - Frontend test mock `lightweight-charts`, vì jsdom không có canvas (`src/pages/MarketPage.test.tsx`).
- XAUUSD mặc định `contract_size=100`, `volume_step=0.01` (`SymbolSpec`).

## Nhật ký

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

## Việc tiếp theo (đề xuất)

Lộ trình: ① dữ liệu giá ✅ → ② biểu đồ ✅ → ③ Technical analyst ✅ → MT5 Gateway chỉ đọc ✅ (đã chạy với MT5 demo thật) → **③b Hồ sơ rủi ro + Kế hoạch giao dịch** → Event & calendar analyst → ④ MarketView đầu tiên → ⑤ Strategy → ⑥ Backtest → ⑦ MT5 thật (để sau).

00. Theo dõi vài ngày ngưỡng R3 (spike 8× trung vị) và R5 trên dữ liệu MetaQuotes-Demo. Người dùng đổi token ingest (token đã lộ trong chat).
0. **Hồ sơ rủi ro + Kế hoạch giao dịch** (làm cùng ③): người dùng nhập vốn, mục tiêu lãi, lỗ tối đa, thông số broker → hệ thống đề xuất SL theo ATR, TP theo R:R, lot, thời gian giữ lệnh ước tính, kết luận khả thi. Hồ sơ lưu có phiên bản. Khi dùng dữ liệu mẫu thì ghi "chỉ minh họa". Mục tiêu người dùng: lãi nhỏ nhưng ổn định (ví dụ 4–5%, chưa chốt theo ngày/tuần/tháng), vốn ví dụ 100$; với lot tối thiểu 0,01 thì 100$ không đủ để rủi ro 1% theo ATR M15, phải báo rõ.
1. **Event & calendar analyst** (ưu tiên cao: chặn giao dịch quanh CPI/NFP/FOMC, tạo cờ `EVENT_WINDOW` mà Risk Engine đã chờ sẵn).
2. **Event Orchestrator đầy đủ:** hiện `TechnicalRunner` polling 15s là bản tối thiểu; cần jobKey, deadline, retry giới hạn, dead-letter.
3. **Fusion đơn giản → `MarketView`** đầu tiên, hiển thị trên Tổng quan. MarketView sinh từ dữ liệu mẫu phải mang cờ để Risk chặn ở SHADOW/LIVE.
4. Strategy Engine và Backtest (replay theo `available_at`, có spread/slippage/phí). Backtest trên dữ liệu mẫu phải đánh dấu "không có giá trị đánh giá".
5. Xác thực API trước khi chạy ngoài localhost.
6. **Giá sống (bid/ask/spread)** từ Gateway sang backend: để hiển thị và để Risk kiểm tra ngay trước khi vào lệnh (bỏ lệnh nếu spread giãn hoặc giá đã chạy xa so với lúc nến đóng). Phân tích vẫn chỉ dùng nến đã đóng. Phải có trước Strategy/đặt lệnh.
7. Gateway: chạy như dịch vụ Windows, đóng gói `.exe` (build trên runner Windows), hàng đợi bền vững; lịch giao dịch từ MT5 (R12). Đặt lệnh: thành phần riêng, làm sau cùng.
