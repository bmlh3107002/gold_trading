# Thiết kế — Làn nhanh (GĐ2 bước 4 — FAST-01..03; 2-C07..C09)

> Tạo 2026-11-14. Ngưỡng: **DEC-20** (người dùng chốt, `docs/giai-doan/GD2-event-orchestrator.md`). Code: `backend/src/gold_trading/risk/blocks.py`, `storage/risk_blocks.py` (4a); 4b–4d sau.

## 1. Quyết định (DEC-20)

| # | Nội dung |
| --- | --- |
| 1 | Số liệu HIGH (CPI, NFP, FOMC, PCE…) → chặn mở lệnh mới **15 phút** kể từ lúc hệ thống nhận số (thêm vào cửa sổ lịch ±15 phút đã có) |
| 2 | Spread > **3 ×** trung vị 60 phút cùng nguồn, kéo dài ≥ 5 giây → chặn; < 1,5 × liên tục 2 phút → gỡ |
| 3 | Chỉ thông cáo chính sách tiền tệ Fed **không có trên lịch** → chặn 15 phút; phát biểu Fed, tin Bộ Tài chính chỉ gắn cờ. RSS tải 15 phút / lần → tin bất ngờ có thể biết trễ tới 15 phút |
| 4 | Ngân sách độ trễ **10 giây** (từ lúc biết tới lúc ghi lệnh cấm); vòng làn nhanh 2 giây; vượt → cảnh báo + mặc định chặn (2-C09) |
| 5 | Lệnh cấm **có hạn, tự hết hạn**, **không gạt công tắc Safety**; mở lệnh mới chỉ khi công tắc ACTIVE **và** không còn lệnh cấm; hành động bảo vệ không bị chặn; web hiện băng cảnh báo |

## 2. Lệnh cấm (4a — 2026-11-14)

- Bảng chỉ-thêm `risk_blocks` (migration 0016): `block_id = sha256(loại | phạm vi | nguyên nhân)[:40]` → cùng nguyên nhân ghi lại không sinh lệnh cấm mới (idempotent, replay). Cột: `kind` (`RELEASE` / `NEWS` / `SPREAD` / `LATENCY`), `scope` (`*` = mọi nguồn, hoặc `feed_id` cho spread), `reason_code` (mã ngắn), `start_at`, `end_at` (`NULL` = tới khi gỡ — spread), `cause_ref`, `created_at`, `policy_version`, `latency_ms`.
- Bảng chỉ-thêm `risk_block_lifts`: gỡ lệnh cấm không có giờ hết (mỗi lệnh cấm gỡ một lần).
- **Có hiệu lực tại t** khi `created_at <= t` (point-in-time: chỉ từ lúc hệ thống biết), `start_at <= t`, `t < end_at` (nếu có), chưa gỡ tới `t`.
- **Safety:** `AccountRegistry.allows_new_orders` = đọc được DB + công tắc ACTIVE + chủ tài khoản không bị khóa + **không có lệnh cấm còn hiệu lực** cho nguồn giá của tài khoản (`*` hoặc đúng `feed_id`). Đọc lệnh cấm lỗi → **chặn**. Công tắc Safety không đổi. API `GET /api/accounts/{id}/status` thêm `entry_blocks` (loại, mã lý do, phạm vi, bắt đầu, hết hạn, nguyên nhân).
- Ghi chú: `RiskEngine` (GĐ5) hiện đọc `SafetySupervisor` trực tiếp — khi nối lệnh thật phải đọc qua `AccountRegistry.allows_new_orders` (có lệnh cấm).
- **Kiểm chứng:** `tests/test_risk_blocks.py` 16 test (bộ nhớ + SQLite + API): idempotent, point-in-time (biết lúc 13:31 thì 13:30:30 chưa chặn), đúng biên `end_at`, phạm vi nguồn, spread mở tới khi gỡ, gỡ một lần, quá khứ không bị viết lại, dữ liệu sai; API: công tắc ACTIVE + lệnh cấm → không mở lệnh, `safety_state` vẫn ACTIVE; lệnh cấm hết hạn → mở lại; spread nguồn khác không áp; đọc lỗi → chặn. Postgres 16: migration lên / xuống, `alembic check` không lệch.
