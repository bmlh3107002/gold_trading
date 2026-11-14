# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-13 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Đang làm: GĐ2 — Event Orchestrator + Làn nhanh** (bắt đầu 2026-11-13, **song song GĐ1 — DEC-19**) → [`docs/giai-doan/GD2-event-orchestrator.md`](docs/giai-doan/GD2-event-orchestrator.md), **kế hoạch + prompt phiên mới: [`docs/ke-hoach/GD2-ke-hoach.md`](docs/ke-hoach/GD2-ke-hoach.md).** Bước 1–3 xong 2026-11-14 (nhật ký sự kiện + job, bộ quét, bộ điều phối, chạy trong backend thay vòng Technical — đường lui `GT_ORCHESTRATOR=0`; mục 1 đạt trên máy 14/11: Technical chạy theo nến). Bước 4 làn nhanh: ngưỡng chốt **DEC-20**; **4a xong** (lệnh cấm có hạn + Safety, `26-…`), **4b–4d xong** 14/11 (cửa sổ lịch + 15 phút sau số HIGH + thông cáo Fed ngoài lịch + spread giãn + độ trễ > 10 giây → Safety chặn mở lệnh mới; băng cảnh báo trang Tổng quan; tuần Tạ ơn chặn cả ngày tới khi có số DOL). **Tiếp: bước 5 (DSH-08)**; kiểm trên máy: mục 2 file kế hoạch GĐ2. GĐ1 code xong, **Gate GĐ1 chưa đóng** (chờ kiểm / ngày công bố — [`docs/ke-hoach/GD1-ke-hoach.md`](docs/ke-hoach/GD1-ke-hoach.md)).
- **GĐ0 đã đóng (2026-11-06).** OPS-06 (CD) hoãn.
- **GĐ1 — quyết định:** DEC-01..07, DEC-14 (chỉ nguồn miễn phí), DEC-18 (bỏ qua vấn đề pháp lý, vẫn không lách chặn kỹ thuật; FRED / GLD / IAU hỏi lại từng nguồn), DEC-19 (GĐ2 song song). Bảng ở file GĐ1.
- **GĐ1 bước 1–10 + 8e BLS xong, đã kiểm trên máy** (mục kiểm 1–21 ở file kế hoạch GĐ1). Nguồn tự chạy: FOMC, BEA, DOL, BLS (lịch chép tay tới 12/2027), H.15, COT, tin Fed + Bộ Tài chính; chỉ số USD tự tính; trang "Nguồn dữ liệu"; dung lượng 1 năm ≈ 0,6 GB (giữ nguyên chính sách).
- **Còn của GĐ1:** Census + ETF (hoãn, quyết ở Gate), **mục 6a tối thứ Hai 16/11** (~23:00 tắt backend → ~07:00 bật; đã hẹn nhắc 22:50), COT sau 22:30 VN 16/11 (nhắc 22:45), DOL 20:30 VN 19/11, giờ broker Lễ Tạ ơn 26–27/11, đo lại dung lượng sau 7 ngày, rồi Gate (≥ 5 ngày chạy liên tục, **NFP 04/12 20:30 VN** — nhắc 20:40).
- Bài học: kiểm nguồn mới **từ máy người dùng** trước khi code; lệnh PowerShell không chứa `\"` hay `$`; đổi `docker-compose.yml` → người dùng tải lại file.
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

Kết quả lần cuối (2026-11-14): backend 1725 passed (2 skipped), ruff sạch; mt5_gateway 206 passed (0.10.3); frontend 92 passed, build đạt.
