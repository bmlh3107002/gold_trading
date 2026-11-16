# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-16 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Đang làm: kiểm trên máy để đóng Gate GĐ1 → GĐ2** theo [`lich-kiem-tren-may.md`](docs/ke-hoach/lich-kiem-tren-may.md) (+ file nhắc `.ics`). 16/11: dựng lại, replay ĐẠT, `h15-bu` + `cot-bu` đạt, thẻ GĐ3/GĐ4 đúng. Tối 16/11: COT + 6a; **đếm ≥ 5 ngày chạy liên tục từ 17/11** (DEC-21). Gate sớm nhất sau NFP 04/12.
- **GĐ1:** code xong; còn kiểm trên máy (DOL 19/11, dung lượng 20/11, Lễ Tạ ơn, NFP 04/12) + quyết ở Gate (Census, ETF, sao lưu).
- **GĐ2:** code xong (DEC-19); Gate: replay lại sau NFP (lần 16/11 mục Technical chưa so thật vì toàn phiên bản cũ) + độ trễ < 10 giây.
- **GĐ3 / GĐ4:** code xong (DEC-22, DEC-23); `nguong` ~20/11, `kiem-mv` 18/11 + 24/11; đóng sau GĐ1 → GĐ2 (→ GĐ3 → GĐ4).
- **Đánh giá độc lập GĐ0–GĐ4** ([file](docs/danh-gia/danh-gia-GD0-GD4.md)), Pha 2: KN-01/02/04 ghi vào GĐ5; KN-16 hoãn. **Code ở nhánh chờ `claude/affectionate-einstein-8ypy59`** (CI đủ 4 job xanh): KN-03 (0021 — lên `develop` sau `kiem-mv` 24/11), KN-13, 14, 15 (`technical-1.6.0`, `regime-1.2.0`), 20 (0022), 21, 05 (0023) — lên `develop` **sau Gate GĐ1 + GĐ2** (người dùng chọn 16/11). KN-26 (CSP) cũng xong ở nhánh chờ. **GĐ5 song song (DEC-28):** kế hoạch duyệt 16/11 (Q1–Q7); **bước 0–2 code xong 16/11** ở nhánh `claude/fervent-hypatia-n3uyfn` (tách từ nhánh chờ): thiết kế 35, RSK-10, RSK-11 (+ migration 0024 phí / lot). **H1–H11 chốt 16/11** (0,25 %/lệnh, heat 0,5 %, lỗ ngày/tuần/tháng 0,75/1,5/3 %, dừng hẳn 5 % — chi tiết nhật ký GĐ5). Chưa lên `develop`; tiếp: code bước 3 (bảng hồ sơ rủi ro). Chưa có lệnh thật.
- **Quản lý vốn (DEC-09):** rủi ro 0,25–0,5 %/lệnh + ngưỡng lỗ ngày/tuần là luật cứng; tài liệu "Quản lý vốn khi giao dịch vàng" **đã nhận 16/11** (số trong đó chỉ là ví dụ) → khung đưa vào kế hoạch GĐ5; số hồ sơ rủi ro người dùng đã chọn đủ H1–H11 (16/11).
- Bài học: kiểm nguồn mới từ máy người dùng trước khi code; PowerShell không `\"` / `$`; đổi compose → tải lại file; **sau mỗi push kiểm CI** (migration 0009); chuỗi lệnh commit phải dừng khi ruff lỗi.
- Bản đồ giai đoạn + bất biến: [`docs/giai-doan/README.md`](docs/giai-doan/README.md).

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

Kết quả lần cuối: `develop` (15/11) backend 2261 passed, frontend 123; nhánh chờ (16/11) backend 2330 passed (2 skipped), frontend 140; **nhánh GĐ5 (16/11) backend 2439 passed (2 skipped)**; ruff sạch, build đạt; mt5_gateway 206 passed (0.10.3).
