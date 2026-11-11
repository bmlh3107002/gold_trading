# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-07 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Giai đoạn hiện tại: GĐ1 — Dữ liệu vào** → [`docs/giai-doan/GD1-du-lieu-vao.md`](docs/giai-doan/GD1-du-lieu-vao.md). **Kế hoạch + checklist + prompt cho phiên mới: [`docs/ke-hoach/GD1-ke-hoach.md`](docs/ke-hoach/GD1-ke-hoach.md).**
- **GĐ0 đã đóng (người dùng xác nhận 2026-11-06).** Trên máy Windows: Docker, Keycloak HTTPS (máy tính + iPhone), MT5 Gateway 9/9, break-glass, chỉ ADMIN/USER (DEC-16), diễn tập sao lưu + khôi phục. OPS-06 (CD) hoãn.
- **DEC-01..07 + DEC-14 đã chốt (2026-11-07)**: chỉ nguồn miễn phí, chi tiết ở bảng quyết định file GĐ1. Người dùng chốt giữ thứ tự đề xuất (bước 1 → 10 trong file kế hoạch).
- **Bước 1 (ING-14 + 1A-C19) xong 2026-11-07** (H1/H4/D1 thật, 0 cách ly). Gateway trên máy: `C:\gold-trading\code\gold_trading-develop`.
- **Bước 2 (1B: CAL-03..05, 1B-C01..C04) xong 2026-11-07** (ngày lễ Mỹ `market/holidays.py`, `GT_BROKER_SPECIAL_HOURS`). Còn treo: đối chiếu giờ broker dịp Lễ Tạ ơn 26–27/11.
- **Bước 3 (1A-C21) xong 2026-11-07**: nến cuối phiên gửi trong `tail_bar`, backend nhận khi hết giờ nến + 2 phút và lịch đóng cửa suốt.
- **Bước 4 (đa tài khoản) chia 5 phần.** Phần 1 MT-12 + GW-09 xong (đã kiểm trên máy). Phần 2 MT-13 (liên kết MT5, migration 0008), phần 3 MT-14 (MT5 khác → MISMATCH chặn ghi) và phần 4 MT-05 (nguồn giá = server + symbol broker, mỗi tài khoản xem giá + analyst theo nguồn của mình, migration 0009 + 0010, Gateway 0.5.0) **code xong, chưa kiểm trên máy**. **Người dùng vắng máy Windows (từ 10/11), đồng ý làm tiếp rồi kiểm sau**: danh sách kiểm ở file kế hoạch, mục "Kiểm trên máy khi người dùng về". **Tiếp theo:** phần 5 MT-15 (nhiều terminal MT5 trên một máy).
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

Kết quả lần cuối (2026-11-11, bước 4 phần 4 GĐ1 — MT-05): backend 597 passed (2 skipped), mt5_gateway 65 passed, frontend 79 passed, ruff/tsc/eslint sạch, build OK; migration 0009/0010 thử trên Postgres 16 thật. (DEC-17: CI `ci_stack.sh` đạt với Keycloak thật, e2e 52/52.)
