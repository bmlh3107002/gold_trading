# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-06 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Giai đoạn hiện tại: GĐ0 — Nền móng** → [`docs/giai-doan/GD0-nen-mong.md`](docs/giai-doan/GD0-nen-mong.md)
- Code + test GĐ0 xong. Trên máy Windows người dùng đã đạt: Docker, đăng nhập, MT5 Gateway 9/9, Tailscale HTTPS máy tính + iPhone, break-glass, **MT-20** (ADMIN tạo người dùng). **DEC-15:** admin chỉ quản trị, token Gateway ẩn với admin. **Còn:** gỡ admin khỏi "Tài khoản chính" + build lại, rồi diễn tập sao lưu + khôi phục (DB-09) → xác nhận đóng GĐ0.
- Sau GĐ0: GĐ1 cần người dùng chốt DEC-01..07 (xem `docs/giai-doan/GD1-du-lieu-vao.md`).
- Bản đồ toàn bộ giai đoạn, nguyên tắc "đi sạch từng giai đoạn", bất biến: [`docs/giai-doan/README.md`](docs/giai-doan/README.md).

## Quyết định đã chốt

| Chủ đề | Quyết định |
| --- | --- |
| Ngôn ngữ | Python cho backend, AI, MT5 Gateway và backtest (không dùng Java) |
| Giao diện | React 18 + TypeScript + Vite (`frontend/`). Theme **CutlotDesk** (terminal tối), i18next tiếng Việt, icon Lucide, font Inter tự host |
| Truy cập | Chỉ web (responsive, điện thoại qua Tailscale Serve HTTPS). Không app mobile/PWA |
| Người dùng | Keycloak (OIDC, BFF). Dùng **nội bộ** (bản thân + người thân), không giới hạn số người (DEC-12, `GT_MULTI_USER_ENABLED=1`). ADMIN tạo người dùng trên Dashboard, mỗi người một tài khoản giao dịch riêng |
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

Kết quả lần cuối (2026-11-06): backend 328 passed, mt5_gateway 26 passed, frontend 58 passed, ruff/tsc/eslint sạch, build OK, `ci_stack.sh` đạt (e2e 27/27 + khôi phục 18/18 + không có bí mật trong log).
