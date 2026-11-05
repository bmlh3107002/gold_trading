# Tiến độ dự án — Gold Trading AI

> File này cập nhật sau **mỗi** đợt làm việc. Phiên sau đọc file này trước, không cần đọc lại toàn bộ repo.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`.

**Cập nhật lần cuối:** 2026-11-05 · **Nhánh làm việc:** `develop`

## Quyết định đã chốt

| Chủ đề | Quyết định |
| --- | --- |
| Ngôn ngữ | Python cho backend, AI, MT5 Gateway và backtest (không dùng Java) |
| Giao diện | React 18 + TypeScript + Vite, nằm chung repo (`frontend/`) |
| Guardian EA | MQL5 |
| Cấu trúc | Monorepo: `backend/`, `mt5_gateway/`, `guardian_ea/`, `frontend/`, `contracts/` |
| Contract | Pydantic ở backend là nguồn sự thật → `contracts/openapi.json` → type TS (`npm run gen:api`) |
| DB dự kiến | PostgreSQL/TimescaleDB (service `db` trong `docker-compose.yml`, profile `db`, chưa dùng) |
| Quản lý Python | `uv` (mỗi package có `uv.lock` riêng) |
| Git | Push lên `develop` (nhánh mặc định trên GitHub). Không tạo PR nếu chưa được yêu cầu |
| Chạy trên máy cá nhân | Docker. `deploy/docker-compose.yml` build thẳng từ GitHub, không cần clone |

## Trạng thái theo thành phần

Chú thích: ✅ xong khung có test · 🟡 có một phần · ⬜ chưa làm

| # | Thành phần | Trạng thái | Vị trí | Ghi chú |
| --- | --- | --- | --- | --- |
| — | Data contract | ✅ | `backend/src/gold_trading/contracts/` | Bất biến (`frozen`), `extra=forbid`, datetime bắt buộc có tz → UTC |
| 02 | Ingestion / point-in-time | 🟡 | `ingestion/point_in_time.py` | Chỉ có store trong bộ nhớ. Chưa có nguồn thật, chưa có DB, chưa có quarantine |
| 03 | Event Orchestrator | ⬜ | `orchestrator/` | |
| 04 | 6 analyst | ⬜ | `analysts/` | Chỉ có contract `AnalystOutput` |
| 05 | Snapshot Builder | ✅ | `intelligence/snapshot_builder.py` | |
| 05 | Data Quality Gate | ✅ | `intelligence/quality_gate.py` | Kiểm tra required/optional, TTL, source_status. Chưa có outlier/schema |
| 05 | Fusion / MarketView | 🟡 | `contracts/market_view.py` | Có contract, chưa có fusion |
| 06 | Strategy Engine | ⬜ | `strategy/` | Có contract `TradeIntent` (validate SL/TP theo chiều lệnh) |
| 07 | Risk Engine | 🟡 | `risk/engine.py` | Có: Safety, hết hạn, risk flags, spread, sizing, hạn mức tổng. Chưa có: margin, correlation, exposure ròng, daily DD |
| 07 | Risk Ledger | 🟡 | `risk/ledger.py` | Reserve/release append-only trong bộ nhớ. Chưa có fill/PnL, chưa đối soát MT5 |
| 08 | Safety Supervisor | ✅ | `safety/supervisor.py` | Chưa nối các trigger tự động (tin nóng, spread, equity) |
| 09 | Order FSM | ✅ | `execution/order_fsm.py` | Chưa có Execution Orchestrator |
| 09 | MT5 Gateway | 🟡 | `mt5_gateway/` | Có Protocol `BrokerAdapter` và map retcode. Chưa có adapter MT5 thật |
| 09 | Guardian EA | 🟡 | `guardian_ea/GuardianEA.mq5` | **Chưa biên dịch, chưa test** |
| 10 | Position Manager / Performance | ⬜ | `position/`, `performance/` | |
| 11 | Training / registry | ⬜ | | |
| 12 | Mode Manager | ✅ | `modes/manager.py` | LIVE khóa, cần approver khác actor và đủ `LIVE_CHECKLIST` |
| 12 | Dashboard | 🟡 | `frontend/` | Có Safety, Mode, MarketView, kill switch, lịch sử. Polling 3s |
| 12 | API | 🟡 | `backend/src/gold_trading/api/app.py` | `/api/health`, `/api/status`, `POST /api/safety`, `POST /api/mode`. **Chưa có xác thực** |
| 12 | Backtest | ⬜ | | |
| — | Docker | ✅ | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `deploy/` | Backend chạy user không root, có healthcheck. Frontend là nginx, proxy `/api` sang `backend:8000`. Dashboard ở `127.0.0.1:8080` |

## Lệnh kiểm tra nhanh

```bash
cd backend && uv sync && uv run pytest -q && uv run ruff check .
```

```bash
cd mt5_gateway && uv sync && uv run pytest -q
```

```bash
cd frontend && npm install && npm run build
```

Kết quả lần cuối: backend 33 passed, mt5_gateway 2 passed, frontend build OK, ruff sạch.

## Lưu ý kỹ thuật

- State của API (Safety, Mode) đang nằm trong bộ nhớ, restart là mất. Cần chuyển sang DB.
- `create_app()` nhận `safety`/`modes` để inject khi test.
- CORS chỉ mở cho `http://localhost:5173`. Vite proxy `/api` sang `localhost:8000`.
- Risk Engine giữ `ledger.lock` khi tính headroom và reserve, để tránh over-allocation khi chạy đồng thời.
- Khi Docker chạy, CORS không cần vì nginx phục vụ dashboard và `/api` cùng origin.
- Backend Dockerfile cài uv bằng pip (không `COPY --from=ghcr.io/...`) để chỉ phụ thuộc Docker Hub và PyPI.
- Khi build Docker trong sandbox cloud: Docker Hub hay trả 429 (dùng `dockerd --registry-mirror=https://mirror.gcr.io`), và cần chèn CA của proxy (`/root/.ccr/ca-bundle.crt`) vào một **bản sao** Dockerfile trong scratchpad. Không commit CA vào repo.
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

## Việc tiếp theo (đề xuất)

1. Ingestion giá MT5 (OHLC M15) và lưu TimescaleDB, kèm quarantine dữ liệu lỗi.
2. Technical analyst (swing, S/R, ATR) → `AnalystOutput`.
3. Event Orchestrator tối thiểu: nến M15 đóng → Technical → Snapshot → Quality Gate.
4. Fusion đơn giản → `MarketView` đầu tiên và hiển thị trên Dashboard.
5. Xác thực API trước khi chạy ngoài localhost.
