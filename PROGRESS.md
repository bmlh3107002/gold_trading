# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-06 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Giai đoạn hiện tại: GĐ0 — Nền móng** → [`docs/giai-doan/GD0-nen-mong.md`](docs/giai-doan/GD0-nen-mong.md)
- **GĐ0: đủ điều kiện Gate, chờ người dùng xác nhận đóng.** Trên máy Windows đã đạt: Docker, đăng nhập Keycloak qua HTTPS (máy tính + iPhone), MT5 Gateway 9/9 có nến, break-glass, MT-20, DEC-16 (chỉ ADMIN/USER), **diễn tập sao lưu + khôi phục cả hai DB (DB-09)**. Ghi cho GĐ1: nến cuối tuần chỉ gửi khi thị trường mở lại.
- Sau GĐ0: GĐ1 cần người dùng chốt DEC-01..07 (xem `docs/giai-doan/GD1-du-lieu-vao.md`).
- Bản đồ toàn bộ giai đoạn, nguyên tắc "đi sạch từng giai đoạn", bất biến: [`docs/giai-doan/README.md`](docs/giai-doan/README.md).

## Quyết định đã chốt

| Chủ đề | Quyết định |
| --- | --- |
| Ngôn ngữ | Python cho backend, AI, MT5 Gateway và backtest (không dùng Java) |
| Giao diện | React 18 + TypeScript + Vite (`frontend/`). Theme **CutlotDesk** (terminal tối), i18next tiếng Việt, icon Lucide, font Inter tự host |
| Truy cập | Chỉ web (responsive, điện thoại qua Tailscale Serve HTTPS). Không app mobile/PWA |
| Người dùng | Keycloak (OIDC, BFF). Dùng **nội bộ**, không giới hạn số người (DEC-12, `GT_MULTI_USER_ENABLED=1`). **Chỉ ADMIN / USER** (DEC-16): ADMIN quản lý tài khoản + duyệt LIVE, không giao dịch; mỗi USER một tài khoản giao dịch + token Gateway riêng |
| Guardian EA | MQL5 |
| Cấu trúc | Monorepo: `backend/`, `mt5_gateway/`, `guardian_ea/`, `frontend/`, `contracts/`, `ops/` |
| Contract | Pydantic ở backend là nguồn sự thật → `contracts/openapi.json` → type TS (`npm run gen:api`) |
| Database | PostgreSQL/TimescaleDB, SQLAlchemy 2 Core + psycopg 3, Alembic |
| Quản lý Python | `uv` (mỗi package có `uv.lock` riêng) |
| Git | Push `develop` (nhánh mặc định). Không tạo PR nếu chưa được yêu cầu |
| Dữ liệu giá | Một cửa nạp `CandleIngestor` cho mọi nguồn (`SAMPLE`/`CSV`/`MT5`); máy người dùng dùng `MT5` (MetaQuotes-Demo) |
| Biểu đồ | `lightweight-charts@4.2.1` (Apache-2.0), có dòng ghi nguồn tradingview.com |
| Chạy trên máy cá nhân | Docker, `deploy/docker-compose.yml` build thẳng từ GitHub. Máy Windows của người dùng: `C:\gold-trading` |

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

Cả hệ thống bằng Docker: `ops/scripts/ci_stack.sh` (chạy trong CI).

Kết quả lần cuối (2026-11-06, DEC-16): backend 329 passed, mt5_gateway 26 passed, frontend 64 passed, ruff/tsc/eslint sạch, build OK, migration 0006 thử trên PostgreSQL 16. CI `ci_stack.sh` đạt với Keycloak thật (e2e 40/40 + khôi phục 14/14 + không có bí mật trong log).
