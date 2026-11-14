# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-14 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Đang làm: GĐ2** (song song GĐ1 — DEC-19) → [`GD2-event-orchestrator.md`](docs/giai-doan/GD2-event-orchestrator.md), kế hoạch + prompt: [`GD2-ke-hoach.md`](docs/ke-hoach/GD2-ke-hoach.md). **Bước 1–5 xong 14/11** (orchestrator, làn nhanh DEC-20, trang Pipeline); kiểm trên máy 14/11 đạt phần thị trường đóng. **Bước 6 Gate:** công cụ replay xong (chưa chạy trên máy), còn đo độ trễ NFP 04/12.
- **GĐ1:** code xong, Gate chưa đóng. Quyết định DEC-01..07, 14, 18, 19, 21 (đếm 5 ngày: gián đoạn < 1 giờ tự hồi phục vẫn tính) — bảng ở file GĐ1. Còn: Census + ETF (quyết ở Gate), 6a tối 16/11, COT 16/11, DOL 19/11, Lễ Tạ ơn, dung lượng sau 7 ngày, ≥ 5 ngày liên tục, NFP 04/12.
- **Lịch việc trên máy + quyết định ở Gate:** [`lich-kiem-tren-may.md`](docs/ke-hoach/lich-kiem-tren-may.md). GĐ0 đóng 2026-11-06 (OPS-06 hoãn).
- **GĐ3 song song (DEC-22):** [`GD3-ke-hoach.md`](docs/ke-hoach/GD3-ke-hoach.md). Xong code 14/11: bước 1 khung chung, 2 Lịch sự kiện, 3 Regime, 4 Macro, 5 COT (API + thẻ); chờ kiểm trên máy (cùng lần dựng lại 16/11). Tiếp: **bước 6 — News (cần chốt DEC-08: nhà cung cấp LLM + ngân sách)**. Nạp bù lịch sử: code xong 14/11 — H.15 (`h15-bu`, đã thử thật: +805 ngày, 0 khác) + COT (`cot-bu`, chạy trên máy người dùng 16/11). Regime 1.1.0: RISK_OFF từ proxy trú ẩn của Macro (14/11). GĐ3 không đóng trước GĐ1/GĐ2.
- **Quản lý vốn (DEC-09 nguyên tắc, 14/11):** ưu tiên rủi ro 0,25–0,5 %/lệnh + ngưỡng lỗ ngày/tuần là luật cứng; 4–5 %/ngày chỉ tham khảo, không dùng để nới rủi ro. **Chờ người dùng gửi lại** tài liệu "Quản lý vốn khi trade vàng" (docx, chưa có trong repo; ZIP ~43 MB chia nhỏ) → áp chi tiết ở GĐ5/6/8/10.
- Bài học: kiểm nguồn mới từ máy người dùng trước khi code; PowerShell không `\"` / `$`; đổi compose → tải lại file.
- Sau mỗi push phải kiểm CI (bài học migration 0009, 2026-11-12).
- ING-18 (forecast): giữ DEC-01; nhập tay forecast để sau.
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

Kết quả lần cuối (2026-11-14): backend 1960 passed (2 skipped), ruff sạch; mt5_gateway 206 passed (0.10.3); frontend 111 passed, build đạt.
