# Tiến độ dự án — Gold Trading AI

> File này **ngắn** và được nạp tự động mỗi lượt (qua `CLAUDE.md`). Chỉ giữ trạng thái hiện tại. Chi tiết nằm theo giai đoạn ở `docs/giai-doan/` — mỗi phiên chỉ mở **file của giai đoạn đang làm**.
> Đặc tả gốc: `docs/huong-dan-chuc-nang/` (01–12). Sơ đồ: `docs/mo-hinh/`. Ghi chú kỹ thuật (bảng thành phần, quy ước code): `docs/ghi-chu-ky-thuat.md` — chỉ đọc mục liên quan.

**Cập nhật lần cuối:** 2026-11-21 · **Nhánh làm việc:** `develop`

## Trạng thái hiện tại

- **Đang làm: kiểm trên máy để đóng Gate GĐ1 → GĐ2** theo [`lich-kiem-tren-may.md`](docs/ke-hoach/lich-kiem-tren-may.md) (+ file nhắc `.ics`). 16/11: dựng lại, replay ĐẠT, `h15-bu` + `cot-bu` đạt. **17/11: 6a ĐẠT** (backend tắt ~8,9 giờ, nạp bù đủ, DB không hở ngoài giờ nghỉ) + **COT chốt 10/11 khớp cftc.gov**; **đếm ≥ 5 ngày chạy liên tục từ 17/11 08:02** (DEC-21). 18/11 `kiem-mv` 24 giờ đạt; 19/11 DOL đạt; 21/11 dung lượng (~1,8 GB/năm, giữ chính sách) + `nguong` (giữ ngưỡng) + cập nhật MT5; sự cố Smart App Control chặn Gateway sau restart → đã tắt, chạy lại. Gate sớm nhất sau NFP 04/12.
- **GĐ1:** code xong; mục 8 (6a) + 17 (COT) đạt 17/11; còn kiểm trên máy (DOL 19/11, dung lượng 20/11, Lễ Tạ ơn, NFP 04/12) + kiểm sao lưu tự động. 17/11 người dùng chốt: bán lẻ = lịch Census chép tay (**code xong**, `census_retail_schedule`), ETF = bỏ hẳn.
- **GĐ2:** code xong (DEC-19); Gate: replay lại sau NFP (lần 16/11 mục Technical chưa so thật vì toàn phiên bản cũ) + độ trễ < 10 giây.
- **GĐ3 / GĐ4:** code xong (DEC-22, DEC-23); `nguong` ~20/11, `kiem-mv` 18/11 + 24/11; đóng sau GĐ1 → GĐ2 (→ GĐ3 → GĐ4).
- **Đánh giá độc lập GĐ0–GĐ4** ([file](docs/danh-gia/danh-gia-GD0-GD4.md)), Pha 2: KN-01/02/04 vào GĐ5; KN-16 hoãn. **17/11: gộp hết vào `develop`** (người dùng chọn): nhánh chờ (KN-03 0021, KN-05 0023, KN-13/14/15, KN-20 0022, KN-21, KN-26) + GĐ5. **Máy người dùng CHƯA dựng lại** — không dựng tới khi Gate GĐ1 + GĐ2 đóng (giữ đợt đếm 5 ngày); sau đó một lần dựng cho tất cả (lịch kiểm).
- **GĐ5 song song (DEC-28)** — code ở `develop` từ 17/11 (migration 0024–0027; máy chưa dựng lại): bước 0–9 xong 16–17/11 (Risk thật RSK-10/11, hồ sơ rủi ro H1–H11, hạn mức, sổ cái paper, chiến lược v1, `cli kha-thi` + trang Rủi ro, sổ tham số + `protocol-1`). **Bước 10 (Gate GĐ5) phần sandbox xong 17/11**: case 5-C01..C16 đủ tên test (5-C13 làm nốt: đọc lại nhịp tim MT5 dưới khóa); RSK-07 xong (Risk tự chặn cờ spread giãn / biến động cao); bảng việc GĐ5 không còn mục dở; hướng dẫn kiểm trên máy bước A–E ở [`GD5-ke-hoach.md`](docs/ke-hoach/GD5-ke-hoach.md). Còn: kiểm trên máy (sau Gate GĐ1 + GĐ2, người dùng chọn lịch), Gate GĐ1→GĐ4 đóng, người dùng xác nhận. Chưa có lệnh thật.
- **GĐ6 song song (DEC-29, 17/11):** chưa code. Kế hoạch [`GD6-ke-hoach.md`](docs/ke-hoach/GD6-ke-hoach.md) **người dùng duyệt 17/11** (Q1–Q7 hỏi khi tới; Q1 = lịch kinh tế lịch sử). Việc đầu (bước 0): xuất XAUUSD M15 + H1/H4/D1 từ MT5 ra `C:\gold-backtest`, đọc thử `import-csv --dry-run` (không mở DB) — cần ≥ 2 năm. Code nhánh `gd6-backtest` (chưa vào `develop` tới sau Gate GĐ1 + GĐ2). Không đóng trước GĐ5.
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

Kết quả lần cuối: `develop` (15/11) backend 2261 passed, frontend 123; nhánh chờ (16/11) backend 2330 passed (2 skipped), frontend 140; **nhánh GĐ5 (17/11, bước 10) backend 2826 passed (3 skipped), frontend 150**; ruff sạch, build đạt; mt5_gateway 206 passed (0.10.3).
