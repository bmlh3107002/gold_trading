# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-12 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Giai đoạn hiện tại: GĐ1 — Dữ liệu vào** → [`docs/giai-doan/GD1-du-lieu-vao.md`](docs/giai-doan/GD1-du-lieu-vao.md). **Kế hoạch + checklist + prompt cho phiên mới: [`docs/ke-hoach/GD1-ke-hoach.md`](docs/ke-hoach/GD1-ke-hoach.md).**
- **GĐ0 đã đóng (người dùng xác nhận 2026-11-06).** Trên máy Windows: Docker, Keycloak HTTPS (máy tính + iPhone), MT5 Gateway 9/9, break-glass, chỉ ADMIN/USER (DEC-16), diễn tập sao lưu + khôi phục. OPS-06 (CD) hoãn.
- **DEC-01..07 + DEC-14 đã chốt (2026-11-07)**: chỉ nguồn miễn phí, chi tiết ở bảng quyết định file GĐ1. Người dùng chốt giữ thứ tự đề xuất (bước 1 → 10 trong file kế hoạch).
- **Bước 1–3 xong + đã kiểm trên máy (2026-11-07):** H1/H4/D1 (ING-14), lịch ngày lễ Mỹ + `GT_BROKER_SPECIAL_HOURS` (1B), nến cuối phiên `tail_bar` (1A-C21). Còn treo: đối chiếu giờ broker dịp Lễ Tạ ơn 26–27/11. Gateway trên máy: `C:\gold-trading\code\gold_trading-develop`.
- **Bước 4–6 code xong 2026-11-12, phần lớn chưa kiểm trên máy** (người dùng vắng máy Windows từ 10/11): bước 4 đa tài khoản (MT-12..15), bước 5 giá sống bid/ask + 6 cặp tiền (migration 0011), bước 6 Gateway bền vững (nạp bù, lệch đồng hồ, băng đỏ mất kết nối, tự chạy cùng Windows; Gateway 0.10.0). Danh sách kiểm: file kế hoạch, mục "Kiểm trên máy khi người dùng về".
- **Bước 7 (khung chung nguồn ngoài, chia 7a–7d):** 7a xong 2026-11-12 — DB-08 + ING-13: bảng `external_records` (migration 0012, point-in-time theo `known_at`), thiết kế `docs/thiet-ke/10-nguon-ngoai.md`. **Tiếp theo: 7b** (ING-30 trạng thái nguồn + TTL).
- **2026-11-12:** sửa migration 0009 hỏng trên TimescaleDB (CI đỏ từ 11/11, nay xanh). Sau mỗi push phải kiểm CI.
- ING-18 (forecast): người dùng giữ DEC-01 (2026-11-12); nhập tay forecast là việc để sau, không thuộc Gate GĐ1.
- **DEC-17 (2026-11-07):** trang Quản trị một USER một dòng, USER xin token → ADMIN cấp. Đã kiểm xong trên máy người dùng.
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

Kết quả lần cuối (2026-11-12, bước 7a GĐ1): backend 738 passed (2 skipped), ruff sạch; mt5_gateway 190 passed, frontend 84 passed (bước 6, lần này không đổi).
