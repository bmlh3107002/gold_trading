# GĐ2 — Event Orchestrator + Làn nhanh: kế hoạch + checklist

> Tạo 2026-11-13. Nguồn sự thật cho mã việc / case: [`docs/giai-doan/GD2-event-orchestrator.md`](../giai-doan/GD2-event-orchestrator.md). Đặc tả: `docs/huong-dan-chuc-nang/03-event-orchestrator.md`. Xong bước nào tick ở **cả hai** file.
>
> **Bắt đầu song song với GĐ1 (DEC-19, người dùng 2026-11-13):** GĐ1 chỉ còn kiểm trên máy / chờ ngày công bố; **Gate GĐ1 chưa đóng**. Việc GĐ1 còn theo dõi ở `GD1-ke-hoach.md` (mục 21 NFP 04/12, 6a, COT 16/11, DOL 19/11, Lễ Tạ ơn, ≥ 5 ngày chạy liên tục…). Dựng lại máy người dùng trong lúc làm GĐ2: chỉ khi cần kiểm, mỗi lần ngắn (Gateway tự nạp bù) — không để backend tắt lâu trong 5 ngày đếm.

## Ý tưởng chính (đề xuất, chốt ở bước 1)

- **Sự kiện suy ra từ dữ liệu đã lưu**, không móc vào từng chỗ nạp: bộ quét đọc nến đã đóng + bản ghi nguồn ngoài theo `known_at` (point-in-time) → sinh sự kiện có khóa ổn định `(loại, chủ thể, phiên bản)`. Nạp lại / chạy lại → cùng sự kiện, cùng khóa → **không nhân đôi** (2-C01), **replay được** từ dữ liệu GĐ1 (Gate GĐ2).
- **Nhật ký sự kiện + nhật ký job chỉ-thêm** (migration mới): trạng thái job tính từ nhật ký (như ING-30) → restart không mất, không chạy lại job đã xong (ORC-08, 2-C05).
- **`jobKey = eventType + subject + eventVersion + analyzerVersion`** (ORC-03); job có deadline, retry giới hạn, backoff, dead-letter (ORC-05).
- **Làn nhanh** chỉ dùng luật, không LLM: CPI / NFP / FOMC vừa ra, spread giãn mạnh, tin chính thức nóng → **cờ rủi ro có hạn** (chặn vào lệnh 10–15 phút) đi thẳng Safety (FAST-01..03). "Bất ngờ so dự báo": **không đủ dữ liệu** (DEC-01, không có forecast).
- Analyst chưa có (Regime, Macro, Positioning, Event, News — GĐ3): job loại đó được ghi nhưng **chưa có bộ xử lý → trạng thái riêng, không giả kết quả**; GĐ3 cắm bộ xử lý vào.

## Thứ tự làm (mỗi bước: code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick → commit → push → CI)

### Bước 1 — Nhật ký sự kiện + job bền vững (ORC-03, ORC-06, ORC-08; 2-C01, 2-C05)
- [x] 1a — Thiết kế `docs/thiet-ke/25-event-orchestrator.md`: loại sự kiện, khóa, phiên bản, `correlationId`, bảng + migration, quy tắc trạng thái job
- [x] 1b — Migration + store SQL + bản bộ nhớ (cùng bộ test), chỉ-thêm (trigger chặn sửa / xóa), TimescaleDB qua CI (2026-11-13: migration 0014, `orchestrator/model.py` + `storage/orchestrator.py`, 36 test; Postgres 16: 8 luồng ghi trùng → đúng 1, trigger + ràng buộc chặn, lên / xuống migration)
- [x] 1c — Bộ quét sinh sự kiện từ dữ liệu GĐ1: nến M15 đóng, số actual / lịch (BLS, BEA, DOL, FOMC), H.15 / chỉ số USD, COT, tin (2026-11-13: `orchestrator/scanner.py`, 13 test, Postgres 35.327 sự kiện = bộ nhớ; chưa chạy tự động — bước 2)

### Bước 2 — Điều phối job (ORC-02, ORC-04, ORC-05; 2-C02, 2-C03, 2-C04)
- [x] Bảng sự kiện → job theo mô hình; thứ tự nhân quả ổn định khi replay; debounce không bỏ sự kiện công bố quan trọng; deadline + retry + backoff + dead-letter; analyst lỗi → MISSING, không dùng output cũ quá hạn (2026-11-14: `orchestrator/dispatcher.py`, migration 0015, 22 test, soát lại 40 kịch bản ngẫu nhiên + Postgres; chưa chạy tự động — bước 3)

### Bước 3 — Thay runner Technical (ORC-01) + vô hiệu MarketView khi output hết hạn (ORC-07, 2-C06)
- [x] Technical chạy qua orchestrator (nến M15 đóng → job); output hết hạn mà không tính lại được → tín hiệu invalidate (MarketView thật ở GĐ4) (2026-11-14: `orchestrator/runner.py`, `OUTPUT_EXPIRED`, `GT_ORCHESTRATOR=0` đường lui; 11 test; Postgres: cùng 24 kết quả như vòng cũ; chờ kiểm trên máy — mục 1)

### Bước 4 — Làn nhanh (FAST-01..03; 2-C07, 2-C08, 2-C09) — ngưỡng: **DEC-20** (2026-11-14)
- [ ] 4a — Lưu lệnh cấm có hạn (chỉ-thêm, migration) + Safety: mở lệnh khi ACTIVE **và** không còn lệnh cấm; bảo vệ lệnh không bị chặn
- [ ] 4b — Chặn theo số liệu HIGH (15 phút từ lúc nhận số) + thông cáo tiền tệ Fed ngoài lịch (15 phút); tin khác chỉ gắn cờ; gộp cửa sổ cùng phút (2-C08); lúc thị trường đóng (2-C07)
- [ ] 4c — Chặn theo spread (> 3 × trung vị 60 phút ≥ 5 giây; bỏ chặn < 1,5 × liên tục 2 phút)
- [ ] 4d — Vòng làn nhanh 2 giây, ngân sách 10 giây (vượt → chặn mặc định, 2-C09), băng cảnh báo trên web
- [ ] Kích hoạt: công bố HIGH (CPI, NFP, FOMC, PCE) theo bảng lịch hợp nhất + số actual; spread giãn mạnh (từ giá theo giây); tin chính thức nóng (nhãn FED / RATES… trong vài phút)
- [ ] Cờ rủi ro có hạn, gộp cửa sổ hai công bố cùng phút (2-C08), sự kiện lúc thị trường đóng (2-C07), vượt ngân sách độ trễ → Safety chặn mặc định (2-C09)
- [ ] Nối Safety: chặn **vào lệnh mới** trong cửa sổ (chưa có lệnh thật tới GĐ9)

### Bước 5 — DSH-08: trang trạng thái pipeline / job / dead-letter

### Bước 6 — Gate GĐ2
- [ ] Replay nhật ký sự kiện từ dữ liệu GĐ1 → kết quả giống hệt; không nhân đôi output
- [ ] Đo độ trễ làn nhanh trên một lần công bố CPI / NFP thật (NFP 04/12 hoặc CPI 10/12) — trong ngân sách
- [ ] Kiểm trên máy người dùng + người dùng xác nhận

## Gate GĐ2 (đủ hết mới đóng; người dùng xác nhận)
- [ ] Mọi việc ORC / FAST / DSH-08 xong, mọi case 2-C01..C09 có test
- [ ] Replay event log từ GĐ1 cho kết quả giống hệt; không nhân đôi output
- [ ] Độ trễ làn nhanh trên một lần công bố CPI / NFP đã ghi nằm trong ngân sách
- [ ] **Gate GĐ1 đã đóng** (DEC-19: GĐ2 làm song song, không đóng GĐ2 trước GĐ1)

## Kiểm trên máy người dùng (điền khi tới)
1. **Bước 1–3 (orchestrator chạy thật):** dựng lại `backend frontend` → `docker compose up -d` → log backend có "Bật Event Orchestrator", không lỗi migration 0014 / 0015 → sau 1 phút log có dòng "Orchestrator: sự kiện mới … job mới …" → trang Thị trường: thẻ Phân tích kỹ thuật vẫn cập nhật mỗi khi có nến M15 mới (khi thị trường mở, từ 06:00 sáng thứ Hai giờ VN). Có sự cố → thêm dòng `GT_ORCHESTRATOR=0` vào `.env` + `docker compose up -d` (quay về cách cũ). **Kiểm trên máy 2026-11-14: đạt** — lần 1 (bản đầu): khởi động > 10 phút (31.507 sự kiện, tạo job từng cái) → sửa debounce khi tạo + theo lô + khôi phục một truy vấn; lần 2: nhịp đầu 2 giây; nến 02:00 giờ VN → log 19:00:08 UTC "sự kiện mới candles 1, job mới 2, chạy SUCCEEDED 1 + NO_HANDLER 1" (Technical + Regime chưa có bộ xử lý), 19:01:08 6 cặp tiền → 6 job MACRO NO_HANDLER; thẻ Phân tích kỹ thuật "Tính tại nến đóng lúc 02:00:00 14/11/2026", "Còn hiệu lực", hết hạn 02:17. Còn: bản bớt log lặp lên máy ở lần dựng lại sau.

## Prompt cho phiên mới
Đọc CLAUDE.md, PROGRESS.md, rồi docs/ke-hoach/GD2-ke-hoach.md và chỉ các mục liên quan của docs/giai-doan/GD2-event-orchestrator.md. Làm bước tiếp theo chưa tick. GĐ1 chưa đóng (DEC-19) — việc GĐ1 còn theo dõi ở GD1-ke-hoach.md. Quy trình như GĐ1: code + test (gồm trường hợp xấu) + soát lại kịch bản riêng → tick ở cả hai file, ghi nhật ký GĐ2, cập nhật PROGRESS.md ngắn gọn → chạy test → commit (nhắc mã việc) → push develop → kiểm CI. Thao tác trên máy Windows: từng lệnh một, lệnh PowerShell không chứa dấu ngoặc kép bên trong hay ký tự $. Người dùng không rành kỹ thuật: tiếng Việt đơn giản, mỗi lần hỏi một câu. Không bao giờ yêu cầu dán mật khẩu / token / khóa API vào chat.
