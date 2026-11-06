# GĐ4 — Snapshot → Data Quality Gate → Fusion → MarketView (đặc tả 05)

> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


| Mã | Việc | TT | Vị trí / ghi chú |
| --- | --- | --- | --- |
| SNP-01 | Snapshot Builder | `[~]` | `intelligence/snapshot_builder.py` — có code + test, **chưa nối luồng** |
| SNP-02 | Lưu snapshot + manifest input để tái dựng | `[ ]` | |
| DQG-01 | Nguồn bắt buộc/tùy chọn, TTL, `sourceStatus` → `REJECTED`/degrade | `[x]` | `intelligence/quality_gate.py` |
| DQG-02 | Schema, outlier, xung đột timestamp | `[ ]` | |
| DQG-03 | Chính sách degrade có phiên bản + audit lý do | `[ ]` | |
| FUS-01 | Fusion bằng luật → `MarketView`; bất đồng → giảm confidence; không lấy đa số đơn thuần khi nguồn tương quan | `[ ]` | Thiết kế ở `docs/thiet-ke/` |
| MKV-01 | Contract `MarketView` | `[x]` | `contracts/market_view.py` |
| MKV-02 | Lưu, hết hạn, invalidate MarketView | `[ ]` | |
| MKV-03 | Hiển thị MarketView trên Tổng quan | `[~]` | Khung có sẵn |

| Mã | Tình huống | Hành vi bắt buộc | TT |
| --- | --- | --- | --- |
| 4-C01 | Thiếu nguồn bắt buộc | `REJECTED`, không có MarketView | `[x]` (Gate) |
| 4-C02 | Nguồn tùy chọn cũ/mất | Giữ snapshot, gắn cờ, hạ confidence theo chính sách | `[~]` |
| 4-C03 | Các analyst bất đồng mạnh | Giảm confidence; có thể `NEUTRAL` | `[ ]` |
| 4-C04 | Đang trong `EVENT_WINDOW` / làn nhanh bật | `riskFlags` truyền xuống MarketView | `[ ]` |
| 4-C05 | MarketView hết hạn trong lúc đang dùng | Lớp sau kiểm lại `expiresAt`, từ chối | `[ ]` |
| 4-C06 | Input từ SAMPLE | MarketView mang cờ, Risk chặn SHADOW/LIVE | `[ ]` |
| 4-C07 | Timestamp các input xung đột | Gắn cờ / REJECTED theo chính sách | `[ ]` |

**Gate GĐ4:** MarketView sinh liên tục trên dữ liệu thật, invalidate đúng, tái dựng được từ manifest, hiển thị trên Tổng quan.
