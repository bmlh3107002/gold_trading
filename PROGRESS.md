# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-13 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Giai đoạn hiện tại: GĐ1 — Dữ liệu vào** → [`docs/giai-doan/GD1-du-lieu-vao.md`](docs/giai-doan/GD1-du-lieu-vao.md). **Kế hoạch + checklist + prompt cho phiên mới: [`docs/ke-hoach/GD1-ke-hoach.md`](docs/ke-hoach/GD1-ke-hoach.md).**
- **GĐ0 đã đóng (người dùng xác nhận 2026-11-06).** Trên máy Windows: Docker, Keycloak HTTPS (máy tính + iPhone), MT5 Gateway 9/9, break-glass, chỉ ADMIN/USER (DEC-16), diễn tập sao lưu + khôi phục. OPS-06 (CD) hoãn.
- **DEC-01..07 + DEC-14 đã chốt (2026-11-07)**: chỉ nguồn miễn phí, chi tiết ở bảng quyết định file GĐ1. Người dùng chốt giữ thứ tự đề xuất (bước 1 → 10 trong file kế hoạch).
- **Bước 1–6 xong + kiểm trên máy** (2026-11-07 / 11-12), trừ **mục 6a** (làm lại qua đêm, hướng dẫn ở file kế hoạch). Còn treo: đối chiếu giờ broker dịp Lễ Tạ ơn 26–27/11. Gateway 0.10.3, `run-all` 2 MT5, thư mục `C:\gold-trading\code\gold_trading-develop`.
- **Bước 7 xong** (khung nguồn ngoài, `docs/thiet-ke/10-…`, `11-…`). **Bước 8:** 8a điều khoản; 8b FOMC; 8c BEA (đã kiểm trên máy); 8d Census **tạm hoãn** (Census chặn Việt Nam; rủi ro thiếu cửa sổ bán lẻ ghi ở Gate); 8e BLS **tạm dừng** (chờ người dùng chụp điều khoản); 8f DOL (chờ kiểm, mục 13). **8g-1..3 xong 2026-11-13**: backend tự chạy FOMC + BEA + DOL (`GT_EXTERNAL_SOURCES`, `16-…`), mức quan trọng có phiên bản, bảng lịch hợp nhất, số chưa biết kéo dài cửa sổ, bảng sửa số (`17-…`, lệnh `cli lich`). **Tiếp: 8g-4** dựng lại trên máy (mục 13 + 14). Bài học: kiểm nguồn mới **từ máy người dùng** trước khi code; đổi `docker-compose.yml` → người dùng tải lại file.
- Sau mỗi push phải kiểm CI (bài học migration 0009, 2026-11-12).
- ING-18 (forecast): người dùng giữ DEC-01 (2026-11-12); nhập tay forecast là việc để sau, không thuộc Gate GĐ1.
- Bản đồ toàn bộ giai đoạn, nguyên tắc "đi sạch từng giai đoạn", bất biến: [`docs/giai-doan/README.md`](docs/giai-doan/README.md).

## Quyết định đã chốt

| Chủ đề | Quyết định |
| --- | --- |
| Ngôn ngữ | Python cho backend, AI, MT5 Gateway và backtest (không dùng Java) |
| Giao diện | React 18 + TypeScript + Vite (`frontend/`). Theme **CutlotDesk** (terminal tối), i18next tiếng Việt, icon Lucide, font Inter tự host |
| Truy cập | Chỉ web (responsive, điện thoại qua Tailscale Serve HTTPS). Không app mobile/PWA |
| Người dùng | Keycloak (OIDC, BFF). Dùng **nội bộ**, không giới hạn số người (DEC-12, `GT_MULTI_USER_ENABLED=1`). **Chỉ ADMIN / USER** (DEC-16): ADMIN quản lý người dùng (thêm/sửa/xóa/khóa) + duyệt LIVE, không giao dịch; mỗi USER một tài khoản giao dịch; USER xin token Gateway, ADMIN cấp (DEC-17) |
| Guardian EA | MQL5 |
| Cấu trúc | Monorepo: `backend/`, `mt5_gateway/`, `guardian_ea/`, `frontend/`, `contracts/`, `ops/` |
| Contract | Pydantic ở backend là nguồn sự thật → `contracts/openapi.json` → type TS (`npm run gen:api`) |
| Database | PostgreSQL/TimescaleDB, SQLAlchemy 2 Core + psycopg 3, Alembic |
| Quản lý Python | `uv` (mỗi package có `uv.lock` riêng) |
| Git | Push `develop` (nhánh mặc định). Không tạo PR nếu chưa được yêu cầu |
| Dữ liệu giá | Một cửa nạp `CandleIngestor` cho mọi nguồn (`SAMPLE`/`CSV`/`MT5`); máy người dùng dùng `MT5` (MetaQuotes-Demo) |
| Biểu đồ | `lightweight-charts@4.2.1` (Apache-2.0), có dòng ghi nguồn tradingview.com |
| Chạy trên máy cá nhân | Docker, `deploy/docker-compose.yml` build thẳng từ GitHub. Máy Windows của người dùng: `C:\gold-trading` |
| Sao lưu thủ công | Người dùng chốt 2026-11-07: **không** sao lưu thủ công trước mỗi lần cập nhật trong lúc phát triển (đang dùng tài khoản demo). Chỉ làm khi chạy thật, sau khi xong các giai đoạn. Container `backup` tự động vẫn chạy như cũ |

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

Kết quả lần cuối (2026-11-13): backend 1203 passed (2 skipped), ruff sạch; mt5_gateway 206 passed (0.10.3); frontend 89 passed, build đạt.
