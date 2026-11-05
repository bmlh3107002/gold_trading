# Gold Trading AI

Hệ thống giao dịch vàng (XAUUSD) theo các lớp tách biệt: dữ liệu → phân tích → chiến lược → rủi ro → thực thi → giám sát. Đặc tả nằm ở [`docs/huong-dan-chuc-nang/`](docs/huong-dan-chuc-nang/README.md), sơ đồ ở [`docs/mo-hinh/`](docs/mo-hinh/).

> Đây là khung ban đầu. LIVE bị khóa mặc định. Không phải khuyến nghị đầu tư.

## Cấu trúc

| Thư mục | Nội dung |
| --- | --- |
| `backend/` | Python 3.11+, FastAPI. Data contract, ingestion, intelligence, strategy, risk, safety, execution, API cho Dashboard |
| `mt5_gateway/` | Adapter Python chạy trên Windows cạnh terminal MT5 |
| `guardian_ea/` | Guardian EA (MQL5), hàng rào cuối tại terminal |
| `frontend/` | Dashboard React + TypeScript + Vite |
| `contracts/` | `openapi.json` xuất từ backend, dùng để sinh type cho frontend |

## Đã có trong khung

- Contract Pydantic bất biến: `NormalizedRecord`, `AnalystOutput`, `Snapshot`, `QualityReport`, `MarketView`, `TradeIntent`, `RiskDecision`, `SafetyTransition`, `OrderRecord`. Bắt buộc datetime có timezone, chuẩn hóa về UTC.
- `PointInTimeStore`: chỉ trả dữ liệu có `ingested_at <= decision_at`, revision không ghi đè lịch sử, append idempotent.
- `SafetySupervisor`: ACTIVE/PAUSED/HALTED, khởi động ở PAUSED, thoát HALTED cần người vận hành duyệt.
- `ModeManager`: LIVE khóa mặc định, cần người duyệt thứ hai và checklist đầy đủ.
- Snapshot Builder + Data Quality Gate (thiếu nguồn bắt buộc thì REJECTED, thiếu nguồn tùy chọn thì hạ confidence).
- Order FSM (UNKNOWN không được gửi lại mù).
- Risk Engine + Risk Ledger: sizing theo khoảng SL, reservation có khóa nên intent đồng thời không vượt hạn mức.
- Dashboard: trạng thái Safety/Mode/MarketView, kill switch, chuyển mode, lịch sử Safety.

Chưa làm (TODO): Event Orchestrator, các analyst, Fusion, Strategy, Position Manager, Performance, Training, lưu trữ DB, adapter MT5 thật, xác thực API.

## Chạy nhanh bằng Docker (không cần cài môi trường)

Chỉ cần Docker Desktop, không cần clone code: xem [`deploy/README.md`](deploy/README.md).

Nếu đã clone repo: `docker compose up -d --build` rồi mở http://localhost:8080.

## Chạy khi phát triển

Cần [uv](https://docs.astral.sh/uv/) và Node 20+.

```bash
cd backend && uv sync && uv run pytest
```

```bash
cd backend && uv run uvicorn gold_trading.api.app:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Mở http://localhost:5173. API hiện **chưa có xác thực**, chỉ chạy ở localhost.

Khi đổi contract hoặc API, sinh lại type cho frontend:

```bash
cd backend && uv run python scripts/export_openapi.py && cd ../frontend && npm run gen:api
```

Database (chưa dùng trong khung): `docker compose --profile db up -d db`.
