# GĐ4 — Snapshot → Data Quality Gate → Fusion → MarketView (đặc tả 05)

> **Bắt đầu 2026-11-15 song song GĐ1 + GĐ2 + GĐ3 (DEC-23).** Kế hoạch: [`docs/ke-hoach/GD4-ke-hoach.md`](../ke-hoach/GD4-ke-hoach.md) (viết 2026-11-15, **chờ người dùng duyệt** trước khi code). Prompt khởi động: `docs/prompts/GD4-bat-dau.md`.
>
> Một phần của bản đồ việc theo giai đoạn (tách từ `CHECKLIST.md` 2026-11-06). Chỉ mục, nguyên tắc và bất biến: [`README.md`](README.md). Trạng thái chung: `PROGRESS.md`. Ghi chú kỹ thuật: `docs/ghi-chu-ky-thuat.md`.


### Quyết định GĐ4

| Mã | Câu hỏi | Người dùng chốt | TT |
| --- | --- | --- | --- |
| DEC-23 | Bắt đầu GĐ4 khi GĐ1/GĐ2/GĐ3 chỉ còn kiểm trên máy / chờ ngày | Người dùng 2026-11-15: **có, làm kế hoạch trước, ở phiên chat mới**. Ngoại lệ có chủ ý cho "đi sạch từng giai đoạn" (như DEC-19, DEC-22). **Không đóng GĐ4 trước GĐ1 → GĐ2 → GĐ3**; việc kiểm trên máy của các giai đoạn trước được ưu tiên | `[x]` 2026-11-15 |
| DEC-24 | Analyst nào bắt buộc cho Quality Gate | Người dùng 2026-11-15: **bắt buộc Technical, Lịch sự kiện, Regime**; tùy chọn Macro, Positioning, News. Lý do: lịch phải có để biết tin lớn; Regime cùng nến giá nên gần như luôn có; News tắt mặc định, Macro/COT chưa đủ lịch sử → nếu bắt buộc sẽ chặn nhiều tuần | `[x]` 2026-11-15 |
| DEC-25 | Fusion có ra hướng khi chưa backtest | Người dùng 2026-11-15: **có — "nghiêng theo luật"** gắn cờ `UNVALIDATED_RULES`; chỉ xem / PAPER / backtest; **Risk chặn SHADOW/LIVE** tới khi backtest GĐ6 đạt + người dùng duyệt | `[x]` 2026-11-15 |
| DEC-26 | Cách gộp khi chưa có trọng số hiệu chỉnh (REG-02 trung tính) | Người dùng 2026-11-15: **giá dẫn, nhóm khác chỉ hạ** — hướng chỉ từ Technical khi Regime `TREND` cùng chiều; Macro / COT / News ngược chiều chỉ hạ confidence hoặc về `NEUTRAL`, không tự tạo hướng; không trọng số đặt tay | `[x]` 2026-11-15 |
| DEC-27 | `pUp` / `pDown` khi chưa hiệu chỉnh | Người dùng 2026-11-15: **để trống (`null`) + cờ `UNCALIBRATED`**; thẻ hiện "Chưa có — chưa hiệu chỉnh"; chỉ điền khi GĐ7 hiệu chỉnh xong | `[x]` 2026-11-15 |

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

## Nhật ký

- **2026-11-15** — **Kế hoạch GĐ4** (chưa code): `docs/ke-hoach/GD4-ke-hoach.md` — 7 bước (thiết kế + sửa hợp đồng MarketView → Snapshot theo nguồn giá + manifest → Quality Gate đủ → Fusion bằng luật → lưu / hết hạn / vô hiệu + Risk chặn SHADOW/LIVE → API + thẻ Tổng quan → Gate). Người dùng chốt DEC-24..27 (bảng trên). Ghi nhận khi đọc code: hợp đồng `MarketView` hiện **bắt buộc** `p_up` / `p_down` và thẻ Tổng quan hiện hai ô này → phải đổi ở bước 1 (DEC-27); `build_snapshot` hiện chưa theo phạm vi nguồn giá và chưa point-in-time theo `known_by`; `QualityPolicy` chưa có phiên bản cụ thể nào dùng thật. Chờ người dùng duyệt kế hoạch.
